-- Minimal fake of the DCS mission-scripting API, just enough to drive skibodcs_mission.lua.
local M = { flags = {} }

coalition = { side = { RED = 1, BLUE = 2 } }
Group = { Category = { AIRPLANE = 0, HELICOPTER = 1, GROUND = 2, SHIP = 3 } }
AI = { Option = { Air = {
  id  = { ROE = 0, REACTION_ON_THREAT = 1, RADAR_USING = 2, ECM_USING = 3, FORMATION = 4 },
  val = { ROE = { WEAPON_FREE = 0, OPEN_FIRE_WEAPON_FREE = 1, OPEN_FIRE = 2, RETURN_FIRE = 3, WEAPON_HOLD = 4 },
          REACTION_ON_THREAT = { NO_REACTION = 0, PASSIVE_DEFENCE = 1, EVADE_FIRE = 2, BYPASS_AND_ESCAPE = 3 } } } } }
world = { event = { S_EVENT_DEAD = 8, S_EVENT_KILL = 28, S_EVENT_CRASH = 5, S_EVENT_LAND = 4,
                    S_EVENT_TAKEOFF = 3, S_EVENT_EJECTION = 6 }, handlers = {} }
function world.addEventHandler(h) world.handlers[#world.handlers + 1] = h end
timer = { getTime = function() return 123.4 end }
M = M
trigger = { action = { setUserFlag = function(n, v) M.flags[n] = v end },
            misc = { getUserFlag = function(n) return M.flags[n] or 0 end } }

M.groups = {}   -- [side][cat] = { group, ... }

function coalition.getGroups(side, cat)
  return (M.groups[side] and M.groups[side][cat]) or {}
end

M.airbases = {}
function coalition.getAirbases(side) return M.airbases[side] or {} end
function M.airbase(o)
  return { getName = function() return o.name end, getID = function() return o.id end,
           getPoint = function() return { x = o.x, y = 0, z = o.z } end,
           getDesc = function() return { category = o.cat or 0 } end }
end
function M.reset() M.groups = {}; M.airbases = {}; M.flags = {}; world.handlers = {}; SKIBO = nil end

function M.unit(o)
  local u = { calls = {}, o = o }
  function u.getPlayerName() return o.player end
  function u.getID() return o.id end
  function u.isExist() return true end
  function u.getName() return o.name or ("u" .. o.id) end
  function u.getTypeName() return o.type or "F-16C" end
  function u.getFuel() return o.fuel or 1.0 end
  function u.getPoint() return { x = o.x or 0, y = 0, z = o.z or 0 } end
  function u.getDesc() return { category = o.cat or 0 } end
  function u.getPosition() local h = math.rad(o.hdg or 0); return { x = { x = math.cos(h), y = 0, z = math.sin(h) } } end
  function u.getCoalition() return o.side or 2 end
  function u.getGroup() return { getName = function() return o.group or "grp" end } end
  if o.boom then u.getController = function() error("controller exploded") end
  else
    local ctl = { options = {}, tasks = {} }
    function ctl:setOption(id, val) self.options[#self.options + 1] = { id, val } end
    function ctl:pushTask(t) self.tasks[#self.tasks + 1] = t end
    function ctl:setTask(t) self.set = t end
    function ctl:resetTask() self.resets = (self.resets or 0) + 1 end
    u.ctl = ctl
    function u.getController() return ctl end
  end
  return u
end

function M.group(units, id)
  local g = {}
  function g.getID() return id or 100 end
  function g.getUnits() return units end
  return g
end

function M.add(side, cat, g)
  M.groups[side] = M.groups[side] or {}
  M.groups[side][cat] = M.groups[side][cat] or {}
  table.insert(M.groups[side][cat], g)
end

function M.eq(a, b, msg)
  if a ~= b then error((msg or "assert") .. ": expected [" .. tostring(b) .. "] got [" .. tostring(a) .. "]", 2) end
end

return M
