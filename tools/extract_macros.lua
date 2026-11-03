-- extract_macros.lua <devices.lua> <command_defs.lua> <Macro_sequencies.lua>  -> JSON on stdout
-- Runs ED's own autostart definition under stubs and dumps start/stop sequences:
--   {"t":sec,"device":id,"command":id,"command_name":..,"value":..} | {"t":..,"message":..} | {"t":..,"check":NAME,"text":..}
local DEV, CMD, MAC = arg[1], arg[2], arg[3]
assert(DEV and CMD and MAC, "usage: extract_macros.lua devices.lua command_defs.lua Macro_sequencies.lua")

local real_dofile = dofile
LockOn_Options = { script_path = "" }
_ = function(s) return s end                                  -- gettext stand-in (ED defines it elsewhere)

local function tagged(tbl_name, key, n)
  return { n = n, name = tbl_name .. "." .. key, __tag = true }
end
local function is_tag(v) return type(v) == "table" and rawget(v, "__tag") == true end

local loaded = {}
dofile = function(path)
  local base = path:match("([%w_]+)%.lua$")
  if base == "command_defs" or base == "devices" then
    if loaded[base] then return end
    loaded[base] = true
    return real_dofile(base == "devices" and DEV or CMD)
  end
  return real_dofile(path)
end

dofile("devices.lua"); dofile("command_defs.lua")
local cmd_tables = {}
for g, v in pairs(_G) do
  if type(g) == "string" and g:match("_commands$") and type(v) == "table" then cmd_tables[g] = v end
end
for g, t in pairs(cmd_tables) do
  local w = {}
  for k, n in pairs(t) do if type(n) == "number" then w[k] = tagged(g, k, n) end end
  _G[g] = w
end

real_dofile(MAC)

local conds = {}                                              -- condition number -> name (e.g. F16_AD_THROTTLE_SET_TO_IDLE)
for g, v in pairs(_G) do
  if type(g) == "string" and type(v) == "number" and g:match("_AD_") then conds[v] = g end
end

local function esc(s) return (tostring(s):gsub('[%c"\\]', function(c)
  local m = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\t'] = '\\t', ['\r'] = '\\r' }
  return m[c] or string.format("\\u%04x", c:byte()) end)) end
local function js(s) return '"' .. esc(s) .. '"' end
local function jn(n) return string.format("%.10g", n) end

local function dump(seq)
  local out = {}
  for _, e in ipairs(seq or {}) do
    local t = e.time or 0
    if e.message then out[#out + 1] = string.format('{"t":%s,"message":%s}', jn(t), js(e.message)) end
    if e.check_condition ~= nil then
      local name = conds[e.check_condition] or tostring(e.check_condition)
      local am = alert_messages and alert_messages[e.check_condition]
      out[#out + 1] = string.format('{"t":%s,"check":%s,"text":%s}', jn(t), js(name), js(am and am.message or ""))
    end
    local act = e.action
    local cid = is_tag(act) and act.n or (type(act) == "number" and act or nil)
    if type(e.device) == "number" and cid then
      out[#out + 1] = string.format('{"t":%s,"device":%s,"command":%s,"command_name":%s,"value":%s}',
        jn(t), jn(e.device), jn(cid), js(is_tag(act) and act.name or ""), jn(tonumber(e.value) or 0))
    end
  end
  return "[" .. table.concat(out, ",\n") .. "]"
end

io.write('{"start":', dump(start_sequence_full), ',\n"stop":', dump(stop_sequence_full), "}\n")
