-- extract_clickables.lua  <devices.lua> <command_defs.lua> <clickabledata.lua>   -> JSON on stdout
-- Runs ED's own cockpit definition files under stubs and records, for every clickable element:
--   key, helper function, hint text, device id+name, command ids+names, cockpit arg numbers.
-- Works on Lua 5.1 / LuaJIT (DCS uses 5.1). Nothing here is copied from the game; only ids are emitted.
local DEV, CMD, CLK = arg[1], arg[2], arg[3]
assert(DEV and CMD and CLK, "usage: extract_clickables.lua devices.lua command_defs.lua clickabledata.lua")

-- ---- "any" object: callable, indexable, arithmetic-safe. Used for helpers and constants we do not model.
local function any_obj(name, recorder)
  local o = {}
  setmetatable(o, {
    __index = function(_, k) return any_obj(name .. "." .. tostring(k)) end,
    __call = function(_, ...)
      if recorder then return recorder(name, ...) end
      return any_obj(name .. "()")
    end,
    __add = function() return any_obj(name) end, __sub = function() return any_obj(name) end,
    __mul = function() return any_obj(name) end, __div = function() return any_obj(name) end,
    __unm = function() return any_obj(name) end, __concat = function() return name end,
  })
  rawset(o, "__any", name)
  return o
end

local function is_any(v) return type(v) == "table" and rawget(v, "__any") ~= nil end

-- ---- tagged command ids (keep the name through to the helper stub)
local function tagged(tbl_name, key, n)
  local t = { n = n, name = tbl_name .. "." .. key, __tag = true }
  local mt = {}
  mt.__add = function(a, b) return (type(a) == "table" and a.n or a) + (type(b) == "table" and b.n or b) end
  setmetatable(t, mt)
  return t
end

local function is_tag(v) return type(v) == "table" and rawget(v, "__tag") == true end

-- ---- environment
local real_dofile = dofile
LockOn_Options = { script_path = "" }
local gettext = { translate = function(s) return s end }
package.preload["i_18n"] = function() return gettext end

local records = {}
local function recorder(fname, ...)
  local el = { fn = fname, args = { ... } }
  records[el] = true
  return el
end

setmetatable(_G, { __index = function(_, k)
  if k:match("^[a-z_0-9]+$") and (k:match("^default_") or k:match("^springloaded_") or k:match("_switch")
      or k:match("_tumb") or k:match("_button") or k:match("_handle") or k:match("_lever") or k:match("^LDG_")
      or k:match("^short_way") or k:match("^multi") or k:match("axis")) or k:match("^LDG_") then
    return any_obj(k, recorder)
  end
  return any_obj(k)
end })

local loaded = {}
dofile = function(path)
  -- clickabledata.lua re-dofiles command_defs/devices itself; run each only once so our tagged tables survive
  local base = path:match("([%w_]+)%.lua$")
  if base == "command_defs" or base == "devices" then
    if loaded[base] then return end
    loaded[base] = true
  end
  if path:match("clickable_defs%.lua$") or path:match("config%.lua$") or path:match("sounds%.lua$") then return end
  if path:match("command_defs%.lua$") then return real_dofile(CMD) end
  if path:match("devices%.lua$") then return real_dofile(DEV) end
  if path:match("clickabledata%.lua$") then return real_dofile(CLK) end
  return real_dofile(path)
end

-- ---- run devices + commands, wrap command tables so ids carry their names
dofile("devices.lua"); dofile("command_defs.lua")
local dev_by_id = {}
for name, id in pairs(rawget(_G, "devices") or {}) do dev_by_id[id] = name end

local cmd_tables = {}
for gname, v in pairs(_G) do
  if type(gname) == "string" and gname:match("_commands$") and type(v) == "table" and not is_any(v) then
    cmd_tables[gname] = v
  end
end
for gname, t in pairs(cmd_tables) do
  local wrapped = {}
  for k, n in pairs(t) do if type(n) == "number" then wrapped[k] = tagged(gname, k, n) end end
  _G[gname] = wrapped
end

dofile("clickabledata.lua")

-- ---- emit JSON
local function esc(s) return (tostring(s):gsub('[%c"\\]', function(c)
  local m = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\t'] = '\\t', ['\r'] = '\\r' }
  return m[c] or string.format("\\u%04x", c:byte()) end)) end

local function jstr(s) return '"' .. esc(s) .. '"' end
local function jnum(n) return string.format("%.10g", n) end

local out = {}
local keys = {}
for k in pairs(elements or {}) do keys[#keys + 1] = k end
table.sort(keys)
for _, key in ipairs(keys) do
  local el = elements[key]
  local fn, hint, device, cmds, nums = "", "", nil, {}, {}
  if records[el] then                              -- helper-built element
    fn = el.fn
    local a = el.args
    hint = type(a[1]) == "string" and a[1] or ""
    if type(a[2]) == "number" then device = a[2] end
    for i = 3, #a do
      local v = a[i]
      if is_tag(v) then cmds[#cmds + 1] = v
      elseif type(v) == "number" and v >= 1 and v < 3000 and #nums < 3 and math.floor(v) == v then nums[#nums + 1] = v end
    end
  else                                             -- hand-written table (class/action/arg...)
    fn = "custom:" .. (type(el.class) == "table" and table.concat((function() local t = {} for _, c in ipairs(el.class) do t[#t+1] = tostring(is_any(c) and rawget(c, "__any") or c) end return t end)(), ",") or "")
    hint = type(el.hint) == "string" and el.hint or ""
    if type(el.device) == "number" then device = el.device end
    local act = el.action
    if is_tag(act) then act = { act } end
    for _, v in ipairs(act or {}) do if is_tag(v) then cmds[#cmds + 1] = v end end
    for _, v in ipairs(el.arg or {}) do if type(v) == "number" then nums[#nums + 1] = v end end
  end
  local cj = {}
  local seen = {}
  for _, c in ipairs(cmds) do
    if not seen[c.name] then seen[c.name] = true
      cj[#cj + 1] = '{"name":' .. jstr(c.name) .. ',"id":' .. jnum(c.n) .. '}' end
  end
  local nj = {}
  for _, n in ipairs(nums) do nj[#nj + 1] = jnum(n) end
  out[#out + 1] = string.format('{"key":%s,"fn":%s,"hint":%s,"device":%s,"device_name":%s,"commands":[%s],"args":[%s]}',
    jstr(key), jstr(fn), jstr(hint), device and jnum(device) or "null",
    device and jstr(dev_by_id[device] or "?") or "null", table.concat(cj, ","), table.concat(nj, ","))
end
io.write("[", table.concat(out, ",\n"), "]\n")
