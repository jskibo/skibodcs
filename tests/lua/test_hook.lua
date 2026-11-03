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
function net.dostring_in(state, code)
  assert(state == "mission")
  local f, err = loadstring(code); if not f then return err, false end
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
  eq(replies[1], '{"detail":"weapons free","id":"w1","ok":true}\n')
  assert(replies[2]:find('"ok":false') and replies[2]:find("not implemented"), replies[2])
  assert(replies[3]:find("unknown type"), replies[3])
end
swapped = false

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
