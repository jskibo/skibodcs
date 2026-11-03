package.path = "tests/lua/?.lua;" .. package.path
local M = require("dcs_mocks")
local eq = M.eq

local WD = "tests/lua/wd/"
os.execute("rm -rf " .. WD .. " && mkdir -p " .. WD .. "Scripts")
do local f = io.open("dcs_hook/skibodcs_mission.lua"); local c = f:read("*a"); f:close()
   f = io.open(WD .. "Scripts/skibodcs_mission.lua", "w"); f:write(c); f:close() end

-- ---- mock DCS GUI-state APIs
lfs = { currentdir = function() return "." end, writedir = function() return WD end,
        mkdir = function(p) os.execute("mkdir -p " .. p) end }
local logs = {}
local swapped = false
local loaded_missions = {}
net = { log = function(m) logs[#logs + 1] = m end,
        load_mission = function(p) loaded_missions[#loaded_missions + 1] = p; return true end }
local fail_next = 0
-- Two Lua states, like DCS: the 'mission' state is only a control layer WITHOUT world/coalition/AI/Group/timer; those live in the
-- scripting sandbox (= this test's globals), reachable only through a_do_script(). a_do_script returns nothing (several DCS
-- builds return an empty string), so the Hook must use the flag mailbox.
local hidden = { world = true, coalition = true, AI = true, Group = true, timer = true }
-- Which flag-reading routes exist differs per DCS build. Default = the author's install: no `trigger` in the 'mission' control state.
W = { mission_trigger = false, a_get = "a_get_flag_value", passthrough = false, server = false, scripting = false }
local function env_for(state)
  local e = setmetatable({}, { __index = function(_, k)
    if hidden[k] then return nil end
    if k == "trigger" and state == "mission" and not W.mission_trigger then return nil end
    return _G[k] end })
  if state == "mission" then
    if W.a_get then e[W.a_get] = function(n) return M.flags[n] or 0 end end
    e.a_do_script = function(code)
      if defer_run and code:find("SKIBO.run", 1, true) then deferred = code; return end      -- sandbox call completes later / never
      local f, err = loadstring(code)
      if not f then sandbox_errors[#sandbox_errors + 1] = err; return end
      local ok, r = pcall(f)
      if not ok then sandbox_errors[#sandbox_errors + 1] = tostring(r); return end
      if W.passthrough then return r end                   -- most builds: return values are NOT passed back
    end
  end
  return e
end
sandbox_errors = {}
defer_run, deferred = false, nil
function net.dostring_in(state, code)
  if state ~= "mission" and not W[state] then return "invalid state name", false end
  if fail_next > 0 then fail_next = fail_next - 1; return "boom: control layer not ready", false end
  local f, err = loadstring(code); if not f then return err, false end
  setfenv(f, env_for(state))
  local ok, r = pcall(f)
  if swapped then return ok, tostring(r) end      -- opposite return order
  return tostring(r), ok
end
-- tiny JSON for flat objects (+ one nested "params" object)
local function enc(v)
  if type(v) == "string" then return '"' .. v:gsub('[\\"]', '\\%0') .. '"' end
  if type(v) ~= "table" then return tostring(v) end
  local keys = {}; for k in pairs(v) do keys[#keys + 1] = k end; table.sort(keys)
  local out = {}; for _, k in ipairs(keys) do out[#out + 1] = enc(k) .. ":" .. enc(v[k]) end
  return "{" .. table.concat(out, ",") .. "}"
end
function net.lua2json(t) return enc(t) end
function net.json2lua(s)
  local pos = 1
  local function ws() pos = s:find("%S", pos) or #s + 1 end
  local val
  local function str() local e = pos + 1; local out = ""
    while s:sub(e, e) ~= '"' do if s:sub(e, e) == "\\" then e = e + 1 end; out = out .. s:sub(e, e); e = e + 1 end
    pos = e + 1; return out end
  function val() ws(); local c = s:sub(pos, pos)
    if c == "{" then pos = pos + 1; local t = {}
      ws(); if s:sub(pos, pos) == "}" then pos = pos + 1; return t end
      while true do ws(); local k = str(); ws(); pos = pos + 1; t[k] = val(); ws()
        local d = s:sub(pos, pos); pos = pos + 1; if d == "}" then return t end end
    elseif c == '"' then return str()
    else local lit = s:match("^[%w%.%-]+", pos); pos = pos + #lit
      if lit == "true" then return true elseif lit == "false" then return false end
      return tonumber(lit) end end
  return val()
end

local clock = 100
DCS = { getRealTime = function() return clock end }
local cb
function DCS.setUserCallbacks(t) cb = t end

-- ---- mock LuaSocket
local sent_udp, replies, inbox = {}, {}, {}
local client = {}
function client:settimeout() end
function client:receive() if #inbox > 0 then return table.remove(inbox, 1) end return nil, "timeout" end
function client:send(s) replies[#replies + 1] = s; return #s end
function client:close() end
local server = { settimeout = function() end, close = function() end,
                 accept = function() return client end }
local udp = { settimeout = function() end, setpeername = function() end, close = function() end,
              send = function(_, s) sent_udp[#sent_udp + 1] = s end }
package.preload["socket"] = function() return { bind = function() return server end, udp = function() return udp end } end

-- ---- run
local function boot()
  M.reset(); sent_udp, replies, inbox = {}, {}, {}
  dofile("dcs_hook/skibodcs_hook.lua")
  assert(cb and cb.onSimulationFrame and cb.onSimulationStart, "callbacks must be registered via DCS.setUserCallbacks")
  cb.onSimulationStart()
  M.add(2, 0, M.group({ M.unit{ id = 1, player = "Skibo" }, M.unit{ id = 2 } }, 5))
end

for _, order in ipairs{ false, true } do
  swapped = order
  boot()
  assert(SKIBO and SKIBO.version, "mission module injected (swapped=" .. tostring(order) .. ")")
  inbox[1] = '{"id":"w1","type":"wingman","intent":"weapons_free","params":{}}'
  inbox[2] = '{"id":"w2","type":"wingman","intent":"barrel_roll","params":{"who":"wingman"}}'
  inbox[3] = '{"id":"w3","type":"cockpit","intent":"x","params":{}}'
  cb.onSimulationFrame()
  eq(#replies, 3)
  local function by_id(id) for _, r in ipairs(replies) do if r:find('"id":"' .. id .. '"', 1, true) then return r end end end
  eq(by_id("w1"), '{"detail":"weapons free","id":"w1","ok":true}\n')            -- answers may arrive in any order; the id matches them
  assert(by_id("w2"):find('"ok":false') and by_id("w2"):find("not implemented"), by_id("w2"))
  assert(by_id("w3"):find("unknown type"), by_id("w3"))
  eq(#sandbox_errors, 0, "sandbox code ran clean: " .. table.concat(sandbox_errors, "; "))
end
swapped = false

-- an injection that fails at onSimulationStart (mission environment not ready) is retried by the poll loop, and logged once
do
  M.reset(); sent_udp, replies, inbox = {}, {}, {}
  fail_next = 2; logs = {}
  dofile("dcs_hook/skibodcs_hook.lua")
  cb.onSimulationStart()                                   -- injection attempt 1 fails
  assert(not SKIBO, "module must not be loaded yet")
  clock = clock + 2; cb.onSimulationFrame()                -- poll: attempt 2 fails (same error: not logged again)
  assert(not SKIBO)
  clock = clock + 2; cb.onSimulationFrame()                -- poll: attempt 3 succeeds
  assert(SKIBO and SKIBO.version, "retry must load the module")
  local fails = 0; for _, l in ipairs(logs) do if l:find("inject failed") then fails = fails + 1 end end
  eq(fails, 1, "the same failure is logged once")
end

-- a sandbox answer that arrives on a LATER frame is still delivered; one that never arrives is reported, not faked
do
  boot()
  defer_run = true
  inbox[1] = '{"id":"d1","type":"wingman","intent":"weapons_free","params":{}}'
  cb.onSimulationFrame()
  eq(#replies, 0, "no answer yet, so no claim of success")
  local run = deferred; deferred = nil; defer_run = false
  assert(run, "the run call was issued")
  env_for("mission").a_do_script(run)                           -- sandbox finally executes it
  clock = clock + 0.2; cb.onSimulationFrame()
  eq(replies[#replies], '{"detail":"weapons free","id":"d1","ok":true}\n')
  boot()
  defer_run = true
  inbox[1] = '{"id":"d2","type":"wingman","intent":"weapons_free","params":{}}'
  cb.onSimulationFrame()
  clock = clock + 4; cb.onSimulationFrame()
  assert(replies[#replies]:find('"ok":false') and replies[#replies]:find("no answer from the mission"), replies[#replies])
  defer_run = false
end

-- the module failing INSIDE the sandbox is diagnosed (flag stays 0) instead of being reported as loaded
do
  M.reset(); sent_udp, replies, inbox, logs = {}, {}, {}, {}
  local real = _G.world; world = nil                     -- sandbox without `world`: module load throws before the ready flag
  dofile("dcs_hook/skibodcs_hook.lua")
  cb.onSimulationStart()
  world = real
  assert(not SKIBO or M.flags["skibo_ready"] == nil, "not ready")
  local msg = table.concat(logs, "\n")
  assert(msg:find("inject failed") and msg:find("Mission script error") and msg:find("only partly"), msg)
end

-- every flag-reading route that exists on some build must be found by the probe; with none the failure names what was tried
local function try_world(cfg, expect)
  local saved = {}; for k, v in pairs(W) do saved[k] = v end
  for k, v in pairs(cfg) do W[k] = v end
  M.reset(); sent_udp, replies, inbox, logs = {}, {}, {}, {}
  dofile("dcs_hook/skibodcs_hook.lua"); cb.onSimulationStart()
  M.add(2, 0, M.group({ M.unit{ id = 1, player = "Skibo" }, M.unit{ id = 2 } }, 5))
  inbox[1] = '{"id":"z1","type":"wingman","intent":"weapons_free","params":{}}'
  cb.onSimulationFrame()
  local msg = table.concat(logs, "\n")
  if expect then
    assert(msg:find("flags are read via " .. expect, 1, true), msg)
    eq(replies[#replies], '{"detail":"weapons free","id":"z1","ok":true}\n')
  else
    assert(msg:find("no flag reader could see the sandbox", 1, true) and msg:find("Tried:", 1, true), msg)
    assert(replies[#replies] and replies[#replies]:find("mission module not loaded"), tostring(replies[#replies]))
  end
  W = saved
end
try_world({}, "mission/a_get_flag_value")
try_world({ a_get = false, mission_trigger = true }, "mission/trigger.misc.getUserFlag")
try_world({ a_get = "a_get_flag" }, "mission/a_get_flag")
try_world({ a_get = false, passthrough = true }, "mission/a_do_script return value")
try_world({ a_get = false, server = true }, "server/trigger.misc.getUserFlag")
try_world({ a_get = false, scripting = true }, "scripting/trigger.misc.getUserFlag")
try_world({ a_get = false }, nil)

-- load_mission: accepted only for existing .miz files under <writedir>/Missions; everything else is refused, nothing loaded
do
  boot()
  os.execute("mkdir -p " .. WD .. "Missions/skibodcs && touch " .. WD .. "Missions/skibodcs/a.miz")
  inbox[1] = '{"id":"m1","type":"load_mission","path":"' .. WD .. 'Missions/skibodcs/a.miz"}'
  inbox[2] = '{"id":"m2","type":"load_mission","path":"/etc/passwd"}'
  inbox[3] = '{"id":"m3","type":"load_mission","path":"' .. WD .. 'Missions/../Scripts/x.miz"}'
  inbox[4] = '{"id":"m4","type":"load_mission","path":"' .. WD .. 'Missions/skibodcs/missing.miz"}'
  cb.onSimulationFrame()
  eq(#replies, 4)
  assert(replies[1]:find('"ok":true') and replies[1]:find("loading a.miz"), replies[1])
  assert(replies[2]:find('"ok":false') and replies[2]:find("refused"), replies[2])
  assert(replies[3]:find("refused"), replies[3])
  assert(replies[4]:find("not found"), replies[4])
  eq(#loaded_missions, 1); eq(loaded_missions[1], WD .. "Missions/skibodcs/a.miz")
end

-- structured params survive the trip: JSON params -> k=v string -> mission state -> option on the right ship
boot()
inbox[1] = '{"id":"p1","type":"wingman","intent":"formation","params":{"who":"wingman","shape":"wedge","spacing":"close"}}'
cb.onSimulationFrame()
eq(replies[#replies], '{"detail":"wedge close","id":"p1","ok":true}\n')

-- heartbeat is throttled (once per second of real time, not per frame)
boot()
local before = #sent_udp
for i = 1, 200 do cb.onSimulationFrame() end
eq(#sent_udp - before, 1, "one heartbeat for 200 frames at a fixed clock")
clock = clock + 1.5; cb.onSimulationFrame()
eq(#sent_udp - before, 2)

-- events flow: mission buffer -> UDP + events.jsonl
local unit = M.unit{ id = 60, name = "sam_site_1-1", group = "sam_site_1", type = "Kub", side = 1 }
world.handlers[1]:onEvent{ id = world.event.S_EVENT_DEAD, initiator = unit }
clock = clock + 2; cb.onSimulationFrame()
local got = false
for _, s in ipairs(sent_udp) do if s:find('"kind":"dead"') and s:find('"group":"sam_site_1"') then got = true end end
assert(got, "event forwarded over UDP")
local f = io.open(WD .. "skibodcs/events.jsonl"); local txt = f:read("*a"); f:close()
assert(txt:find("sam_site_1"), "event appended to events.jsonl")

print("HOOK LUA OK")
