-- Export module: argument read-back + cockpit click, with mocked Export API
package.path = "tests/lua/?.lua;" .. package.path
local replies, lines, clicks = {}, {}, {}
lfs = { writedir = function() return "tests/lua/wd/" end, currentdir = function() return "." end }
local client = { settimeout = function() end, close = function() end,
                 send = function(_, s) replies[#replies + 1] = s end }
function client:receive() if #lines > 0 then return table.remove(lines, 1) end return nil, "timeout" end
local server = { settimeout = function() end, close = function() end, accept = function() return client end }
local udp = { settimeout = function() end, setpeername = function() end, close = function() end, send = function() end }
package.preload["socket"] = function() return { bind = function() return server end, udp = function() return udp end } end
local args = { [362] = 1.0 }
function GetDevice(id)
  if id == 0 then return { get_argument_value = function(_, a) return args[a] end } end
  return { performClickableAction = function(_, c, v) clicks[#clicks + 1] = { id, c, v } end }
end
local ic = {}
function LoSetCommand(c, v) ic[#ic + 1] = { c, v } end
dofile("dcs_hook/skibodcs_export.lua")
LuaExportStart()
lines[1] = "R,362"; lines[2] = "R,999"; lines[3] = "7,3001,1.0"; lines[4] = "C,311"; lines[5] = "C,2004,-1.0"
LuaExportBeforeNextFrame()
assert(replies[1] == "ARG,362,1.0000\n", tostring(replies[1]))
assert(replies[2] == "ARG,999,nil\n", tostring(replies[2]))
assert(#clicks == 1 and clicks[1][2] == 3001 and clicks[1][3] == 1.0, "click dispatched")
assert(#ic == 2 and ic[1][1] == 311 and ic[1][2] == nil and ic[2][1] == 2004 and ic[2][2] == -1.0, "iCommand passthrough")
print("EXPORT LUA OK")
