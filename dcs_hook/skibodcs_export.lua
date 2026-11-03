-- skibodcs_export.lua  (UNTESTED against a live DCS; field names follow the Export API as documented)
-- Load from your EXISTING Saved Games\DCS\Scripts\Export.lua by appending ONE line:
--   pcall(dofile, lfs.writedir() .. [[Scripts\skibodcs_export.lua]])
-- It chains any callbacks already defined (DCS-BIOS, Tacview, SRS...) instead of replacing them,
-- and every call is wrapped in pcall so a bug here can never take DCS down.

local prev = {
  Start    = LuaExportStart,
  Stop     = LuaExportStop,
  Before   = LuaExportBeforeNextFrame,
  Activity = LuaExportActivityNextEvent,
}

local TELEMETRY_PORT, COMMAND_PORT, HZ = 14501, 14500, 2
local M2FT, MS2KT, RAD2DEG = 3.28084, 1.943844, 57.29578
local MAX_OBJS = 120

-- The Export environment does NOT put LuaSocket on the search path (the Hook state is set up the same way below). Without this the
-- require threw, the module died silently inside pcall(dofile) and every cockpit command failed with "lost the link to DCS".
package.path  = package.path  .. ";" .. lfs.currentdir() .. "/LuaSocket/?.lua"
package.cpath = package.cpath .. ";" .. lfs.currentdir() .. "/LuaSocket/?.dll"

local function elog(msg) pcall(function() log.write("SKIBODCS", log.INFO, "skibodcs export: " .. tostring(msg)) end) end

local ok_s, socket = pcall(require, "socket")
if not ok_s then elog("LuaSocket not found, telemetry and cockpit commands are disabled: " .. tostring(socket)); socket = nil end
local udp, server, client
local bound_logged

local function safe(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  elog("error: " .. tostring(r))
end

local function ensure_sockets()
  if not socket then return end
  if not udp then
    udp = socket.udp(); udp:setpeername("127.0.0.1", TELEMETRY_PORT); udp:settimeout(0)
  end
  if not server then
    local err
    server, err = socket.bind("127.0.0.1", COMMAND_PORT)
    if server then server:settimeout(0) elseif not bound_logged then elog("cannot listen on TCP " .. COMMAND_PORT .. ": " .. tostring(err)) end
  end
  if server and udp and not bound_logged then
    bound_logged = true
    elog("ready: telemetry UDP " .. TELEMETRY_PORT .. ", cockpit commands TCP " .. COMMAND_PORT)
  end
end

local function num(v) return string.format("%.6f", v or 0) end

local function snapshot()
  local me = LoGetSelfData(); if not me or not me.LatLongAlt then return nil end
  local gs = (LoGetTrueAirSpeed() or 0) * MS2KT
  -- Locked target id (UNVERIFIED field name: LoGetLockedTargetInformation()[1].ID)
  local lock = safe(function()
    local t = LoGetLockedTargetInformation and LoGetLockedTargetInformation()
    if t and t[1] and t[1].ID then return tostring(t[1].ID):gsub('[^%w]', '') end
  end) or ""
  local parts = { string.format(
    '{"own":{"model":"%s","lat":%s,"lon":%s,"alt_ft":%.0f,"hdg":%.1f,"gs_kt":%.0f,"lock":"%s"},"objs":[',
    tostring(me.Name or ""):gsub('[^%w%-_ ]', ''), num(me.LatLongAlt.Lat), num(me.LatLongAlt.Long),
    (me.LatLongAlt.Alt or 0) * M2FT, (me.Heading or 0) * RAD2DEG, gs, lock) }
  local objs, n = LoGetWorldObjects() or {}, 0
  for id, o in pairs(objs) do
    if n >= MAX_OBJS then break end
    local lla = o.LatLongAlt
    if lla and o.Type and o.Type.level1 == 1 then          -- level1 == 1: aircraft
      local coal = (o.Coalition == "Enemies") and "red" or "blue"
      parts[#parts + 1] = string.format('%s{"id":"%s","lat":%s,"lon":%s,"alt_ft":%.0f,"hdg":%.1f,"coal":"%s","air":true}',
        n > 0 and "," or "", tostring(id), num(lla.Lat), num(lla.Long), (lla.Alt or 0) * M2FT,
        (o.Heading or 0) * RAD2DEG, coal)
      n = n + 1
    end
  end
  parts[#parts + 1] = "]}"
  return table.concat(parts)
end

local function pump_commands()
  if not server then return end
  if not client then client = server:accept(); if client then client:settimeout(0) end end
  if not client then return end
  while true do
    local line, err = client:receive("*l")
    if not line then if err == "closed" then client = nil end; break end
    local ic, iv = line:match("^C,(%d+),?([%d%.%-]*)$")          -- C,<iCommand>[,<value>]: e.g. native autostart/autostop
    if ic then
      safe(function() if iv ~= "" then LoSetCommand(tonumber(ic), tonumber(iv)) else LoSetCommand(tonumber(ic)) end end)
    end
    local ra = line:match("^R,(%d+)$")                       -- read-back: R,<cockpit arg> -> ARG,<arg>,<value>
    if ra then
      local val = safe(function() return GetDevice(0):get_argument_value(tonumber(ra)) end)
      client:send(string.format("ARG,%s,%s\n", ra, val and string.format("%.4f", val) or "nil"))
    end
    local d, c, v = line:match("^(%d+),(%d+),([%d%.%-]+)$")
    if d then
      local dev = GetDevice(tonumber(d))
      if dev then dev:performClickableAction(tonumber(c), tonumber(v)) end
    end
  end
end

function LuaExportStart()
  if prev.Start then safe(prev.Start) end
  safe(ensure_sockets)
end

function LuaExportBeforeNextFrame()
  if prev.Before then safe(prev.Before) end
  safe(pump_commands)
end

function LuaExportActivityNextEvent(t)
  local nxt = t + 1.0 / HZ
  if prev.Activity then
    local p = safe(prev.Activity, t)
    if p and p < nxt then nxt = p end
  end
  safe(function()
    ensure_sockets()
    local s = snapshot()
    if s and udp then udp:send(s) end
  end)
  return nxt
end

function LuaExportStop()
  if prev.Stop then safe(prev.Stop) end
  if client then client:close(); client = nil end
  if server then server:close(); server = nil end
  if udp then udp:close(); udp = nil end
end
