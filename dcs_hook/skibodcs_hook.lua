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

local function inject_module()
  local f = io.open(MODULE, "r")
  if not f then log("missing " .. MODULE); return end
  local code = f:read("*a"); f:close()
  local r, err = in_mission(code)
  if r then mission_loaded = true; log("mission module loaded: " .. r) else log("inject failed: " .. tostring(err)) end
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

local function handle_line(line)
  local cmd = net.json2lua(line)
  if type(cmd) ~= "table" then return end
  if cmd.type ~= "wingman" then reply({ id = cmd.id, ok = false, detail = "unknown type" }); return end
  if not mission_loaded then inject_module() end
  if not mission_loaded then reply({ id = cmd.id, ok = false, detail = "mission module not loaded" }); return end
  local p = cmd.params or {}
  local call = string.format("return SKIBO.cmd(%q,%q,%q,%q)", tostring(cmd.intent or ""),
      tostring(p.mode or ""), tostring(p.weapon or "auto"), tostring(p.target_id or ""))
  local r, err = in_mission(call)
  if not r then reply({ id = cmd.id, ok = false, detail = "dostring failed: " .. tostring(err) }); return end
  local status, detail = r:match("^(%a+):(.*)$")
  reply({ id = cmd.id, ok = (status == "ok"), detail = detail or r })
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

local function poll_events()
  if not mission_loaded then return end
  local r = in_mission("return SKIBO.drain()")
  if r and r ~= "" then
    for line in r:gmatch("[^\n]+") do
      local kind, unit, group, utype, coal, t = line:match("^([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)$")
      if kind then
        local ev = { type = "event", kind = kind, unit = unit, group = group, utype = utype, coalition = tonumber(coal), t = tonumber(t) }
        append_event(ev)
        if udp then udp:send(net.lua2json(ev)) end
      end
    end
  end
  if udp then udp:send('{"type":"heartbeat"}') end
end

local cb = {}

function cb.onSimulationStart()
  mission_loaded = false
  safe(ensure_sockets)
  safe(inject_module)
end

function cb.onSimulationFrame()
  safe(pump_commands)
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
