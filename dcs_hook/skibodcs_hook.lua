-- skibodcs_hook.lua  ->  Saved Games\DCS\Scripts\Hooks\skibodcs_hook.lua
-- Runs in the Hook (GUI/server) Lua state. It owns the sockets and the files, and reaches the
-- mission state only through net.dostring_in('mission', ...). Callbacks MUST be registered with
-- DCS.setUserCallbacks (plain global functions are never called).
-- UNVERIFIED in a live sim; the Lua logic is exercised against mocked DCS APIs in tests/lua.

local COMMAND_PORT, STATUS_PORT = 14510, 14511
local POLL_SECONDS = 1.0

package.path  = package.path  .. ";" .. lfs.currentdir() .. "/LuaSocket/?.lua"
package.cpath = package.cpath .. ";" .. lfs.currentdir() .. "/LuaSocket/?.dll"

local function log(msg) pcall(net.log, "skibodcs: " .. tostring(msg)) end
local function safe(f, ...) local ok, r = pcall(f, ...); if ok then return r end; log(r) end

local ok_s, socket = pcall(require, "socket")
if not ok_s then log("LuaSocket not found: " .. tostring(socket)); socket = nil end

local server, client, udp
local mission_loaded, last_poll = false, 0
local MODULE = lfs.writedir() .. "Scripts/skibodcs_mission.lua"
local EVENTS = lfs.writedir() .. "skibodcs/events.jsonl"

-- net.dostring_in returns (result, success); tolerate the opposite order just in case.
local function in_mission(code)
  local a, b = net.dostring_in("mission", code)
  if type(a) == "boolean" then a, b = b, a end
  if b == false then return nil, tostring(a) end
  return tostring(a or "")
end

-- The 'mission' state is a control layer: `world`, `coalition`, `AI` do NOT exist there. Code that needs them is run in the
-- mission scripting sandbox with a_do_script(); answers come back through mission user flags (see skibodcs_mission.lua).
local function long_bracket(code)                     -- a Lua long string literal that cannot be broken by the code inside
  local n = 0
  while code:find("]" .. string.rep("=", n) .. "]", 1, true) do n = n + 1 end
  local eq = string.rep("=", n)
  return "[" .. eq .. "[" .. code .. "]" .. eq .. "]"
end

local NF = 24
local function read_flags_code(prefix)               -- Lua source (for the 'mission' state) returning "seq,f1,...,f24"
  return string.format('local t = {} for i = 0, %d do t[#t + 1] = trigger.misc.getUserFlag("skibo_%s_" .. i) end return table.concat(t, ",")', NF, prefix)
end

local function decode_flags(str)                     -- "seq,f1..f24" -> seq, text
  local parts = {}
  for v in tostring(str or ""):gmatch("[^,]+") do parts[#parts + 1] = tonumber(v) or 0 end
  if #parts < NF + 1 then return nil end
  local out = {}
  for i = 2, NF + 1 do
    local n = math.floor(parts[i] + 0.5)
    for _, div in ipairs({ 1000000, 10000, 100, 1 }) do
      local c = math.floor(n / div) % 100
      if c == 99 then return parts[1], table.concat(out) end
      out[#out + 1] = string.char(c + 32)
    end
  end
  return parts[1], table.concat(out)
end

local last_inject_err
local function inject_module()
  local f = io.open(MODULE, "r")
  if not f then log("missing " .. MODULE); return end
  local code = f:read("*a"); f:close()
  local r, err = in_mission("a_do_script(" .. long_bracket(code) .. ") return trigger.misc.getUserFlag('skibo_ready')")
  local ok = r and (tonumber(r) or 0) >= 5
  if ok then
    mission_loaded = true; last_inject_err = nil; log("mission module loaded in the scripting sandbox")
  else
    local why = err or ("module not ready (flag=" .. tostring(r) .. "); look for 'Mission script error' lines just above in dcs.log")
    if why ~= last_inject_err then last_inject_err = why; log("inject failed (will retry every poll): " .. tostring(why)) end
  end
end

local function ensure_sockets()
  if not socket then return end
  if not server then
    server = socket.bind("127.0.0.1", COMMAND_PORT)
    if server then server:settimeout(0) end
  end
  if not udp then
    udp = socket.udp(); udp:setpeername("127.0.0.1", STATUS_PORT); udp:settimeout(0)
  end
end

local function reply(tbl)
  if client then client:send(net.lua2json(tbl) .. "\n") end
end

-- params table -> "k=v;k2=v2" (sanitised); the mission state has no JSON decoder
local function param_string(p)
  local keys = {}
  for k in pairs(p) do keys[#keys + 1] = k end
  table.sort(keys)
  local out = {}
  for _, k in ipairs(keys) do
    local kk = tostring(k):gsub("[^%w_]", "")
    local vv = tostring(p[k]):gsub("[^%w_%-]", "")
    out[#out + 1] = kk .. "=" .. vv
  end
  return table.concat(out, ";")
end

-- Start a mission file. Only .miz files under Saved Games\\DCS\\Missions are accepted. net.load_mission is documented for
-- servers; whether it starts a mission from the single-player GUI is UNVERIFIED (the reply says what DCS answered).
local function handle_load_mission(cmd)
  local path = tostring(cmd.path or ""):gsub("\\", "/")
  local base = (lfs.writedir():gsub("\\", "/")) .. "Missions/"
  if path:sub(1, #base):lower() ~= base:lower() or not path:lower():match("%.miz$") or path:find("..", 1, true) then
    reply({ id = cmd.id, ok = false, detail = "refused: only .miz files under Saved Games/DCS/Missions" }); return
  end
  local f = io.open(path, "rb")
  if not f then reply({ id = cmd.id, ok = false, detail = "mission file not found" }); return end
  f:close()
  reply({ id = cmd.id, ok = true, detail = "loading " .. path:match("[^/]+$") })     -- answer first: loading tears the sockets down
  local ok, r = pcall(net.load_mission, path)
  if not ok or r == false then log("load_mission failed: " .. tostring(r)) end
end

local cmd_queue, pending, seq_counter = {}, nil, 0

local function handle_line(line)
  local cmd = net.json2lua(line)
  if type(cmd) ~= "table" then return end
  if cmd.type == "load_mission" then handle_load_mission(cmd); return end
  if cmd.type ~= "wingman" then reply({ id = cmd.id, ok = false, detail = "unknown type" }); return end
  if not mission_loaded then inject_module() end
  if not mission_loaded then reply({ id = cmd.id, ok = false, detail = "mission module not loaded" }); return end
  cmd_queue[#cmd_queue + 1] = { id = cmd.id, intent = tostring(cmd.intent or ""), ps = param_string(cmd.params or {}) }
end

-- One command at a time: run it in the sandbox, then read the answer from the "res" flags. If the answer is not there yet
-- (the sandbox call may complete on a later frame) keep polling for up to 3 real seconds; never claim success without an answer.
local function service_commands(now)
  while true do
    if not pending then
      local c = table.remove(cmd_queue, 1)
      if not c then return end
      seq_counter = seq_counter + 1
      pending = { id = c.id, seq = seq_counter, t0 = now }
      local run = string.format("SKIBO.run(%d, %q, %q)", pending.seq, c.intent, c.ps)
      local _, err = in_mission("a_do_script(" .. long_bracket(run) .. ")")
      if err then reply({ id = c.id, ok = false, detail = "dostring failed: " .. err }); pending = nil end
    end
    if pending then
      local r = in_mission(read_flags_code("res"))
      local seq, text = decode_flags(r)
      if seq == pending.seq then
        local status, detail = tostring(text):match("^(%a+):(.*)$")
        reply({ id = pending.id, ok = (status == "ok"), detail = detail or text })
        pending = nil
      elseif now - pending.t0 > 3 then
        reply({ id = pending.id, ok = false, detail = "no answer from the mission (paused, or the module is not running)" })
        pending = nil
      else
        return                                        -- try again next frame
      end
    end
  end
end

local function pump_commands()
  if not server then return end
  if not client then
    client = server:accept()
    if client then client:settimeout(0) end
  end
  if not client then return end
  while true do
    local line, err = client:receive("*l")
    if not line then
      if err == "closed" then client = nil end
      break
    end
    safe(handle_line, line)
  end
end

local function append_event(tbl)
  lfs.mkdir(lfs.writedir() .. "skibodcs")
  local f = io.open(EVENTS, "a")
  if f then f:write(net.lua2json(tbl), "\n"); f:close() end
end

local last_ev_seq, ack_next = 0, nil
local function poll_events()
  if not mission_loaded then inject_module() end       -- the sandbox can be incomplete at onSimulationStart
  if not mission_loaded then return end
  local call = string.format("SKIBO.flush(%s)", ack_next and tostring(ack_next) or "nil")
  local r, err = in_mission("a_do_script(" .. long_bracket(call) .. ") " .. read_flags_code("ev"))
  if r then
    local seq, text = decode_flags(r)
    if seq and seq > last_ev_seq and text and text ~= "" then
      last_ev_seq = seq
      for line in text:gmatch("[^%^]+") do
        local kind, unit, group, utype, coal, t = line:match("^([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)$")
        if kind then
          local ev = { type = "event", kind = kind, unit = unit, group = group, utype = utype, coalition = tonumber(coal), t = tonumber(t) }
          append_event(ev)
          if udp then udp:send(net.lua2json(ev)) end
        end
      end
    end
    ack_next = (seq and seq > 0) and seq or nil        -- acknowledge the packet we just stored; the sandbox then drops those lines
  end
  if udp then udp:send('{"type":"heartbeat"}') end
end

local cb = {}

function cb.onSimulationStart()
  mission_loaded = false
  cmd_queue, pending, last_ev_seq, ack_next = {}, nil, 0, nil
  safe(ensure_sockets)
  safe(inject_module)
end

function cb.onSimulationFrame()
  safe(pump_commands)
  safe(service_commands, DCS.getRealTime())
  local now = DCS.getRealTime()
  if now - last_poll >= POLL_SECONDS then
    last_poll = now
    safe(poll_events)
  end
end

function cb.onSimulationStop()
  mission_loaded = false
  if client then client:close(); client = nil end
  if server then server:close(); server = nil end
  if udp then udp:close(); udp = nil end
end

DCS.setUserCallbacks(cb)
log("hook registered")
