-- extract_clickables.lua  <devices.lua> <command_defs.lua> <clickabledata.lua>   -> JSON on stdout
-- Runs ED's own cockpit definition files under stubs and records, for every clickable element:
--   key, helper function, hint text, device id+name, command ids+names, cockpit arg numbers.
-- Works on Lua 5.1 / LuaJIT (DCS uses 5.1). Nothing here is copied from the game; only ids are emitted.
local DEV, CMD, CLK, DRAW = arg[1], arg[2], arg[3], arg[4]   -- DRAW (optional): draw_args.lua with cockpit_args (F-14)
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
    __unm = function() return any_obj(name) end, __concat = function(a, b)
      local function str(x) if type(x) == "table" and rawget(x, "__any") then return rawget(x, "__any") end return tostring(x) end
      return str(a) .. str(b)
    end,
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
  local el = { fn = fname, args = { ... }, nargs = select("#", ...), class = {} }   -- class: modules post-process elements ("Sanitize tumbs")
  records[el] = true
  return el
end

-- Every unknown global is callable AND records the call: ED's helper names vary per module
-- (default_*, springloaded_*, mpd_button, lighted_pushbutton...), constants are simply never called.
setmetatable(_G, { __index = function(_, k) return any_obj(k, recorder) end })

local loaded = {}
dofile = function(path)
  path = tostring(path)
  for _, base in ipairs{ "command_defs", "devices" } do
    if path:match(base .. "%.lua$") then
      if loaded[base] then return end                     -- clickabledata re-dofiles these; keep our tagged tables
      loaded[base] = true
      return real_dofile(base == "devices" and DEV or CMD)
    end
  end
  if path:match("clickabledata%.lua$") then return real_dofile(CLK) end
  if path:match("draw_args%.lua$") and DRAW and DRAW ~= "" then return real_dofile(DRAW) end
  -- clickable_defs/config/sounds/paths/draw_args ...: not needed (or not supplied); unknown names resolve to harmless stubs
  return
end

-- Modules that define their OWN helper functions (Heatblur F-14) return plain tables. Wrap every global function the
-- file defines so each returned element remembers which helper built it and with what arguments.
setmetatable(_G, { __index = getmetatable(_G).__index,
  __newindex = function(t, k, v)
    if type(v) == "function" and type(k) == "string" and k ~= "__" and not k:match("^_") then
      rawset(t, k, function(...)
        local r = v(...)
        if type(r) == "table" and not is_any(r) then
          rawset(r, "__helper", k); rawset(r, "__args", { ... }); rawset(r, "__nargs", select("#", ...))
        end
        return r
      end)
    else
      rawset(t, k, v)
    end
  end })

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
  local fn, hint, device, cmds, nums, params = "", "", nil, {}, {}, {}
  local crew, arg_explicit = nil, nil
  local helper = rawget(el, "__helper")
  if records[el] or helper then                    -- helper-built element (ED stub OR the module's own helper)
    fn = helper or el.fn
    local a = helper and rawget(el, "__args") or el.args
    local na = (helper and rawget(el, "__nargs") or el.nargs) or #a          -- nil holes (default args) must not truncate the scan
    -- AH-64D helpers take a crew selector first (CREW.PLT / CREW.CPG); others start with the hint string
    if is_any(a[1]) and tostring(rawget(a[1], "__any")):match("^CREW%.") then crew = tostring(rawget(a[1], "__any")):gsub("^CREW%.", "") end
    local hi = 1
    while a[hi] ~= nil and type(a[hi]) ~= "string" and hi < 3 do hi = hi + 1 end
    hint = type(a[hi]) == "string" and a[hi] or ""
    if type(a[hi + 1]) == "number" then device = a[hi + 1] end
    for ai = 1, na do                              -- F-14 passes pilot_only / rio_only / pilot_and_rio tables
      local v = a[ai]
      if is_any(v) then                            -- F-4E: pilot_only / wso_only live in clickable_dsl.lua (not supplied) => stubs
        local nm = tostring(rawget(v, "__any"))
        if nm == "pilot_only" then crew = "PLT" elseif nm == "wso_only" or nm == "rio_only" then crew = "WSO" end
      elseif type(v) == "table" and not is_tag(v) then
        if v == rawget(_G, "pilot_only") then crew = "PLT" elseif v == rawget(_G, "rio_only") then crew = "RIO" end
      end
    end
    if records[el] then                              -- ED-style helpers: the cockpit arg number follows the command id(s)
      local i = hi + 2                               -- (modules with their own helpers, e.g. the F-14, hide it in cockpit_args)
      while is_tag(a[i]) do i = i + 1 end
      if type(a[i]) == "number" then arg_explicit = a[i] end
    end
    for i = hi + 2, na do
      local v = a[i]
      if is_tag(v) then cmds[#cmds + 1] = v
      elseif type(v) == "number" and v >= 1 and v < 3000 and #nums < 3 and math.floor(v) == v then nums[#nums + 1] = v end
      if type(v) == "number" then params[#params + 1] = v end
    end
    if arg_explicit == nil and type(rawget(el, "arg")) == "table" then   -- module-defined helper: trust the element it actually returned
      local fa = rawget(el, "arg")[1]
      if type(fa) == "number" then arg_explicit = fa end
    end
  else                                             -- hand-written table (class/action/arg...)
    fn = "custom:" .. (type(el.class) == "table" and table.concat((function() local t = {} for _, c in ipairs(el.class) do t[#t+1] = tostring(is_any(c) and rawget(c, "__any") or c) end return t end)(), ",") or "")
    hint = type(el.hint) == "string" and el.hint or ""
    if type(el.device) == "number" then device = el.device end
    local act = el.action
    if is_tag(act) then act = { act } end
    for _, v in ipairs(act or {}) do if is_tag(v) then cmds[#cmds + 1] = v end end
    for _, v in ipairs(el.arg or {}) do if type(v) == "number" then nums[#nums + 1] = v; params[#params + 1] = v end end
    if type(el.arg) == "table" and type(el.arg[1]) == "number" then arg_explicit = el.arg[1] end
  end
  local cj = {}
  local seen = {}
  for _, c in ipairs(cmds) do
    if not seen[c.name] then seen[c.name] = true
      cj[#cj + 1] = '{"name":' .. jstr(c.name) .. ',"id":' .. jnum(c.n) .. '}' end
  end
  local nj, pj = {}, {}
  for _, n in ipairs(nums) do nj[#nj + 1] = jnum(n) end
  for _, n in ipairs(params) do pj[#pj + 1] = jnum(n) end
  out[#out + 1] = string.format('{"key":%s,"fn":%s,"hint":%s,"device":%s,"device_name":%s,"commands":[%s],"args":[%s],"params":[%s],"crew":%s,"arg":%s}',
    jstr(key), jstr(fn), jstr(hint), device and jnum(device) or "null",
    device and jstr(dev_by_id[device] or "?") or "null", table.concat(cj, ","), table.concat(nj, ","), table.concat(pj, ","), crew and jstr(crew) or "null", arg_explicit and jnum(arg_explicit) or "null")
end
io.write("[", table.concat(out, ",\n"), "]\n")
