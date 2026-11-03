-- skibodcs_mission.lua
-- Runs INSIDE the mission scripting state. The Hook injects it via net.dostring_in('mission', ...).
-- Mission state has no sockets and no io (sanitized): it only answers calls and buffers events;
-- the Hook polls SKIBO.drain() and does the file/network work.
-- UNVERIFIED in a live sim: AI task/option behaviour, getPlayerName() in single player,
-- and whether Export object ids equal Object:getID(). Everything is pcall-wrapped.

SKIBO = SKIBO or {}
local S = SKIBO
S.version = "0.3"
S.events = S.events or {}
local MAX_EVENTS = 500

local function sides() return { coalition.side.RED, coalition.side.BLUE } end
local function cats() return { Group.Category.AIRPLANE, Group.Category.HELICOPTER } end

-- ---------- lookup helpers
function S.find_player()
  for _, side in ipairs(sides()) do
    for _, cat in ipairs(cats()) do
      for _, g in ipairs(coalition.getGroups(side, cat) or {}) do
        for _, u in ipairs(g:getUnits() or {}) do
          local ok, pn = pcall(u.getPlayerName, u)
          if ok and pn and pn ~= "" then return u, g, side end
        end
      end
    end
  end
end

function S.wingmen()
  local p, g, side = S.find_player()
  if not p then return nil, {}, nil end
  local out, pid = {}, p:getID()
  for _, u in ipairs(g:getUnits() or {}) do
    if u:getID() ~= pid and u:isExist() then out[#out + 1] = u end
  end
  return p, out, side
end

function S.find_unit_by_id(id)
  local want = tostring(id)
  local all = { Group.Category.AIRPLANE, Group.Category.HELICOPTER, Group.Category.GROUND, Group.Category.SHIP }
  for _, side in ipairs(sides()) do
    for _, cat in ipairs(all) do
      for _, g in ipairs(coalition.getGroups(side, cat) or {}) do
        for _, u in ipairs(g:getUnits() or {}) do
          if tostring(u:getID()) == want then return u end
        end
      end
    end
  end
end

local function nearest_hostile_air(p, my_side)
  local enemy = (my_side == coalition.side.BLUE) and coalition.side.RED or coalition.side.BLUE
  local pp, best, bd = p:getPoint(), nil, math.huge
  for _, cat in ipairs(cats()) do
    for _, g in ipairs(coalition.getGroups(enemy, cat) or {}) do
      for _, u in ipairs(g:getUnits() or {}) do
        if u:isExist() then
          local q = u:getPoint()
          local d = math.sqrt((q.x - pp.x) ^ 2 + (q.z - pp.z) ^ 2)
          if d < bd then best, bd = u, d end
        end
      end
    end
  end
  return best, bd
end

-- ---------- tasking
local function each_controller(ws, fn)
  local n = 0
  for _, w in ipairs(ws) do
    local c = w:getController()
    if c then fn(c, w); n = n + 1 end
  end
  return n
end

local function push_engage(ws, tgt)
  local cat = tgt:getDesc().category          -- 0 airplane, 1 helicopter, 2 ground, 3 ship
  local id = (cat == 0 or cat == 1) and "EngageUnit" or "AttackUnit"
  return each_controller(ws, function(c)
    c:pushTask({ id = id, params = { unitId = tgt:getID() } })
  end)
end

-- Intents that have a handler below. Everything else must answer "err:not implemented"
-- (never a fake success: the app would announce an action that did not happen).
S.IMPLEMENTED = { weapons_free = true, weapons_hold = true, engage_my_target = true,
                  engage_nearest = true, status = true }

function S._cmd(intent, mode, weapon, target_id)
  local p, ws, side = S.wingmen()
  if not p then return "err:no player unit found" end
  if not S.IMPLEMENTED[intent] then return "err:not implemented: " .. tostring(intent) end
  if #ws == 0 then return "err:no wingman" end

  if intent == "weapons_free" or intent == "weapons_hold" then
    local val = (intent == "weapons_free") and AI.Option.Air.val.ROE.WEAPON_FREE
                                             or AI.Option.Air.val.ROE.WEAPON_HOLD
    each_controller(ws, function(c) c:setOption(AI.Option.Air.id.ROE, val) end)
    return "ok:" .. (intent == "weapons_free" and "weapons free" or "weapons hold")

  elseif intent == "engage_my_target" then
    if not target_id or target_id == "" then return "err:no target locked" end
    local tgt = S.find_unit_by_id(target_id)
    if not tgt then return "err:target not found" end
    local n = push_engage(ws, tgt)
    return n > 0 and ("ok:engaging " .. tostring(tgt:getTypeName())) or "err:no controller"

  elseif intent == "engage_nearest" then
    local tgt, d = nearest_hostile_air(p, side)
    if not tgt then return "err:no hostile contacts" end
    local n = push_engage(ws, tgt)
    return n > 0 and string.format("ok:engaging nearest, %d miles", math.floor(d / 1852 + 0.5)) or "err:no controller"

  elseif intent == "status" then
    local parts = {}
    for _, w in ipairs(ws) do parts[#parts + 1] = string.format("%d%%", math.floor((w:getFuel() or 0) * 100 + 0.5)) end
    return string.format("ok:%d wingman, fuel %s", #ws, table.concat(parts, ", "))
  end
  return "err:unknown intent"
end

function S.cmd(intent, mode, weapon, target_id)
  local ok, r = pcall(S._cmd, intent, mode, weapon, target_id)
  if ok then return r end
  return "err:" .. tostring(r)
end

-- ---------- event buffer (campaign results)
local H = {}
local NAMES = {}
local function reg(const, name) if const then NAMES[const] = name end end
reg(world.event.S_EVENT_DEAD, "dead");       reg(world.event.S_EVENT_KILL, "kill")
reg(world.event.S_EVENT_CRASH, "crash");     reg(world.event.S_EVENT_LAND, "land")
reg(world.event.S_EVENT_TAKEOFF, "takeoff"); reg(world.event.S_EVENT_EJECTION, "eject")

local function safe(f, ...) local ok, r = pcall(f, ...); if ok then return r end end

function H:onEvent(e)
  local kind = e and NAMES[e.id]
  if not kind or not e.initiator then return end
  local u = e.initiator
  local group = safe(function() return u:getGroup():getName() end) or ""
  local line = table.concat({ kind, tostring(safe(u.getName, u) or ""), group,
                              tostring(safe(u.getTypeName, u) or ""),
                              tostring(safe(u.getCoalition, u) or ""),
                              string.format("%.0f", timer.getTime()) }, "|")
  S.events[#S.events + 1] = line
  if #S.events > MAX_EVENTS then table.remove(S.events, 1) end
end

if not S.handler then S.handler = H; world.addEventHandler(H) end

function S.drain()
  local out = table.concat(S.events, "\n")
  S.events = {}
  return out
end

return "skibodcs mission module " .. S.version
