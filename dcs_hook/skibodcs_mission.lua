-- skibodcs_mission.lua
-- Runs in the MISSION SCRIPTING SANDBOX (where `world`, `coalition`, `AI`, `trigger` exist) - the same place as DO SCRIPT.
-- net.dostring_in('mission', ...) does NOT reach it: that state is a control layer without those globals (confirmed by a real
-- log: "attempt to index global 'world' (a nil value)"). The Hook therefore injects this file with a_do_script(), and the
-- two sides talk through mission USER FLAGS (the one channel every DCS version supports): text is packed 4 characters per
-- flag (2 decimal digits per character, 99 = end) into skibo_<res|ev>_1..24, with the sequence number written last to
-- skibo_<res|ev>_0. The sandbox has no sockets and no io; the Hook owns the files and the network.
-- UNVERIFIED in a live sim: AI task/option behaviour, getPlayerName() in single player,
-- and whether Export object ids equal Object:getID(). Everything is pcall-wrapped.

SKIBO = SKIBO or {}
local S = SKIBO
S.version = "0.5"
S.events = S.events or {}
local MAX_EVENTS = 500

local function sides() return { coalition.side.RED, coalition.side.BLUE } end
local function cats() return { Group.Category.AIRPLANE, Group.Category.HELICOPTER } end

-- ---------- flag mailbox (sandbox -> Hook)
local NF = 24                                         -- flags per message: up to 4*NF-1 = 95 characters
S.NF = NF
function S.encode(text)
  local codes = {}
  for i = 1, math.min(#text, NF * 4 - 1) do
    local b = text:byte(i)
    if b < 32 or b > 126 then b = 63 end             -- '?'
    codes[#codes + 1] = b - 32
  end
  codes[#codes + 1] = 99                              -- terminator; the rest is padding
  while #codes % 4 ~= 0 do codes[#codes + 1] = 99 end
  local flags = {}
  for i = 1, #codes, 4 do
    flags[#flags + 1] = codes[i] * 1000000 + codes[i + 1] * 10000 + codes[i + 2] * 100 + codes[i + 3]   -- < 1e8, well inside int32
  end
  return flags
end

function S.put(prefix, seq, text)
  local flags = S.encode(tostring(text or ""))
  for i = 1, NF do trigger.action.setUserFlag("skibo_" .. prefix .. "_" .. i, flags[i] or 99999999) end
  trigger.action.setUserFlag("skibo_" .. prefix .. "_0", seq)                  -- commit marker written last
end

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
  if not p then return nil, {}, nil, nil end
  local out, pid = {}, p:getID()
  for _, u in ipairs(g:getUnits() or {}) do
    if u:getID() ~= pid and u:isExist() then out[#out + 1] = u end
  end
  return p, out, side, g
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

local function heading_of(u)                      -- radians, 0 = north, clockwise
  local ok, pos = pcall(u.getPosition, u)
  if ok and pos and pos.x then return math.atan2(pos.x.z, pos.x.x) end
  return 0
end

local function nearest_hostile_ground(p, my_side, max_m, arc_rad)
  local enemy = (my_side == coalition.side.BLUE) and coalition.side.RED or coalition.side.BLUE
  local pp, hd = p:getPoint(), heading_of(p)
  local best, bd = nil, math.huge
  for _, g in ipairs(coalition.getGroups(enemy, Group.Category.GROUND) or {}) do
    for _, u in ipairs(g:getUnits() or {}) do
      if u:isExist() then
        local q = u:getPoint()
        local dx, dz = q.x - pp.x, q.z - pp.z
        local d = math.sqrt(dx * dx + dz * dz)
        local off = math.abs(((math.atan2(dz, dx) - hd) + math.pi) % (2 * math.pi) - math.pi)
        if d <= max_m and off <= arc_rad and d < bd then best, bd = u, d end
      end
    end
  end
  return best, bd
end

local function nearest_friendly_airfield(u, side)
  local pp, best, bd = u:getPoint(), nil, math.huge
  for _, ab in ipairs(coalition.getAirbases and coalition.getAirbases(side) or {}) do
    local okd, desc = pcall(ab.getDesc, ab)
    if okd and desc and desc.category == 0 then      -- 0 = airdrome (not helipad / ship)
      local q = ab:getPoint()
      local d = math.sqrt((q.x - pp.x) ^ 2 + (q.z - pp.z) ^ 2)
      if d < bd then best, bd = ab, d end
    end
  end
  return best, bd
end

local function route_task(points) return { id = "Mission", params = { route = { points = points } } } end
local function wp(x, z, alt, speed, kind, extra)
  local t = { x = x, y = z, alt = alt, speed = speed, alt_type = "BARO", type = kind or "Turning Point",
              action = kind == "Land" and "Landing" or "Turning Point" }
  for k, v in pairs(extra or {}) do t[k] = v end
  return t
end

-- ---------- tasking
-- Option ids/values follow the DCS scripting API as used by MOOSE (Controllable.lua, Enums.lua);
-- task ids/params follow pydcs (dcs/task.py). Not yet exercised against a live sim.
-- AI.Option is resolved lazily: at onSimulationStart the mission environment may not have defined `AI` yet
-- (seen in a real log: "attempt to index global 'AI' (a nil value)"), and a load-time failure kills the whole module.
local OPT, ROE_MAP, ROT_MAP
local RADAR_MAP = { off = 0, attack_only = 1, search = 2, continuous = 3 }   -- RADAR_USING
local ECM_MAP   = { off = 0, lock = 1, detected = 2, always = 3 }            -- ECM_USING
local function ai_ready()
  if OPT then return true end
  if not (AI and AI.Option and AI.Option.Air) then return false end
  OPT = AI.Option.Air
  ROE_MAP = { free = OPT.val.ROE.WEAPON_FREE, hold = OPT.val.ROE.WEAPON_HOLD,
              return_fire = OPT.val.ROE.RETURN_FIRE, open_fire = OPT.val.ROE.OPEN_FIRE }
  ROT_MAP = { none = OPT.val.REACTION_ON_THREAT.NO_REACTION, passive = OPT.val.REACTION_ON_THREAT.PASSIVE_DEFENCE,
              evade = OPT.val.REACTION_ON_THREAT.EVADE_FIRE, escape = OPT.val.REACTION_ON_THREAT.BYPASS_AND_ESCAPE }
  return true
end
local NEEDS_AI = { weapons_free = true, weapons_hold = true, roe = true, radar = true, ecm = true, reaction = true, formation = true }
-- FORMATION values (MOOSE ENUMS.Formation.FixedWing): shape -> { close, open, group }
local FORM = {
  line_abreast = { 65537, 65538, 65539 },  trail        = { 131073, 131074, 131075 },
  wedge        = { 196609, 196610, 196611 }, echelon_right = { 262145, 262146, 262147 },
  echelon_left = { 327681, 327682, 327683 }, finger_four  = { 393217, 393218, 393219 },
  spread       = { 458753, 458754, 458755 }, vic          = { 917505, 917506, nil },
}
local SPACING = { close = 1, open = 2, group = 3 }

local function parse(ps)
  local t = {}
  for k, v in tostring(ps or ""):gmatch("([%w_]+)=([^;]*)") do t[k] = v end
  return t
end

-- who: flight (all AI in the player's group) | wingman (#2) | element (#3,#4) | "2" "3" "4"
local function select_units(ws, who)
  who = (who == nil or who == "") and "flight" or who
  if who == "flight" then return ws end
  if who == "wingman" then return { ws[1] } end
  if who == "element" then local t = {}; if ws[2] then t[#t + 1] = ws[2] end; if ws[3] then t[#t + 1] = ws[3] end; return t end
  local n = tonumber(who)
  if n and n >= 2 and ws[n - 1] then return { ws[n - 1] } end
  return {}
end

local function each_controller(units, fn)
  local n = 0
  for _, w in ipairs(units) do
    local c = w:getController()
    if c then fn(c, w); n = n + 1 end
  end
  return n
end

local function set_option(units, id, val)
  return each_controller(units, function(c) c:setOption(id, val) end)
end

local function push_engage_unit(units, tgt)
  local cat = tgt:getDesc().category          -- 0 airplane, 1 helicopter, 2 ground, 3 ship
  local id = (cat == 0 or cat == 1) and "EngageUnit" or "AttackUnit"
  return each_controller(units, function(c) c:pushTask({ id = id, params = { unitId = tgt:getID() } }) end)
end

local function push_engage_types(units, types)
  return each_controller(units, function(c)
    c:pushTask({ id = "EngageTargets", params = { targetTypes = types, priority = 0 } })
  end)
end

-- Intents with a handler below. Everything else must answer "err:not implemented"
-- (never a fake success: the app would announce an action that did not happen).
S.IMPLEMENTED = { weapons_free = true, weapons_hold = true, roe = true, radar = true, ecm = true, reaction = true,
                  formation = true, engage_my_target = true, engage_nearest = true, engage_bandits = true,
                  engage_ground = true, engage_sead = true, cover_me = true, rejoin = true, status = true,
                  rtb = true, cleared_hot = true, break_left = true, break_right = true }

function S._cmd(intent, ps)
  local P = parse(ps)
  local p, ws, side, pg = S.wingmen()
  if not p then return "err:no player unit found" end
  if not S.IMPLEMENTED[intent] then return "err:not implemented: " .. tostring(intent) end
  if NEEDS_AI[intent] and not ai_ready() then return "err:AI options not available in the mission yet" end
  if #ws == 0 then return "err:no wingman" end
  local us = select_units(ws, P.who)
  if #us == 0 then return "err:no such flight member" end

  if intent == "weapons_free" or intent == "weapons_hold" or intent == "roe" then
    local level = (intent == "weapons_free") and "free" or (intent == "weapons_hold") and "hold" or P.level
    local v = ROE_MAP[level or ""]
    if not v then return "err:unknown ROE '" .. tostring(level) .. "'" end
    set_option(us, OPT.id.ROE, v)
    return "ok:" .. (level == "free" and "weapons free" or level == "hold" and "weapons hold" or level:gsub("_", " "))

  elseif intent == "radar" or intent == "ecm" or intent == "reaction" then
    local map, id = ({ radar = RADAR_MAP, ecm = ECM_MAP, reaction = ROT_MAP })[intent],
                    ({ radar = OPT.id.RADAR_USING, ecm = OPT.id.ECM_USING, reaction = OPT.id.REACTION_ON_THREAT })[intent]
    local v = map[P.level or ""]
    if v == nil then return "err:unknown " .. intent .. " level '" .. tostring(P.level) .. "'" end
    set_option(us, id, v)
    return "ok:" .. intent .. " " .. P.level:gsub("_", " ")

  elseif intent == "formation" then
    local f = FORM[P.shape or ""]
    local sp = SPACING[P.spacing or "open"]
    if not f or not sp or not f[sp] then return "err:unknown formation '" .. tostring(P.shape) .. "/" .. tostring(P.spacing) .. "'" end
    set_option(us, OPT.id.FORMATION, f[sp])
    return "ok:" .. P.shape:gsub("_", " ") .. " " .. (P.spacing or "open")

  elseif intent == "engage_my_target" then
    if not P.target_id or P.target_id == "" then return "err:no target locked" end
    local tgt = S.find_unit_by_id(P.target_id)
    if not tgt then return "err:target not found" end
    local n = push_engage_unit(us, tgt)
    return n > 0 and ("ok:engaging " .. tostring(tgt:getTypeName())) or "err:no controller"

  elseif intent == "engage_nearest" then
    local tgt, d = nearest_hostile_air(p, side)
    if not tgt then return "err:no hostile contacts" end
    local n = push_engage_unit(us, tgt)
    return n > 0 and string.format("ok:engaging nearest, %d miles", math.floor(d / 1852 + 0.5)) or "err:no controller"

  elseif intent == "engage_bandits" or intent == "engage_ground" or intent == "engage_sead" then
    local types = ({ engage_bandits = { "Air" }, engage_ground = { "Ground Units" }, engage_sead = { "Air Defence" } })[intent]
    local n = push_engage_types(us, types)
    return n > 0 and ("ok:" .. intent:gsub("_", " ")) or "err:no controller"

  elseif intent == "cover_me" then
    local n = each_controller(us, function(c)
      c:pushTask({ id = "Escort", params = { groupId = pg:getID(), engagementDistMax = 60000,
                                              targetTypes = { "Air" }, pos = { x = -200, y = -100, z = -500 } } })
    end)
    return n > 0 and "ok:covering you" or "err:no controller"

  elseif intent == "rejoin" then
    local n = each_controller(us, function(c)
      c:resetTask()
      c:pushTask({ id = "Follow", params = { groupId = pg:getID(), pos = { x = -150, y = 0, z = 150 } } })
    end)
    return n > 0 and "ok:rejoining" or "err:no controller"

  elseif intent == "rtb" then
    local n, home = 0, nil
    for _, w in ipairs(us) do
      local ab = nearest_friendly_airfield(w, side)
      if ab then
        local a, q = w:getPoint(), ab:getPoint()
        local c = w:getController()
        if c then
          c:setTask(route_task({ wp(a.x, a.z, a.y, 200), wp(q.x, q.z, 0, 120, "Land", { airdromeId = ab:getID() }) }))
          n = n + 1; home = home or ab:getName()
        end
      end
    end
    if n == 0 then return "err:no friendly airfield found" end
    return "ok:returning to " .. tostring(home)

  elseif intent == "break_left" or intent == "break_right" then
    local sign = (intent == "break_left") and -1 or 1
    local n = each_controller(us, function(c, w)
      local a, h = w:getPoint(), heading_of(w) + sign * math.pi / 2
      local d = 18520                                  -- 10 nm out, same altitude
      c:setTask(route_task({ wp(a.x, a.z, a.y, 250), wp(a.x + d * math.cos(h), a.z + d * math.sin(h), a.y, 250) }))
    end)
    return n > 0 and ("ok:breaking " .. (sign < 0 and "left" or "right")) or "err:no controller"

  elseif intent == "cleared_hot" then
    local tgt
    if P.target_id and P.target_id ~= "" then tgt = S.find_unit_by_id(P.target_id) end
    if not tgt then tgt = nearest_hostile_ground(p, side, 25 * 1852, math.rad(60)) end
    if not tgt then return "err:no ground target in front of you" end
    local n = each_controller(us, function(c)
      c:pushTask({ id = "AttackUnit", params = { unitId = tgt:getID(), groupAttack = true } })
    end)
    return n > 0 and ("ok:attacking " .. tostring(tgt:getTypeName())) or "err:no controller"

  elseif intent == "status" then
    local parts = {}
    for _, w in ipairs(us) do parts[#parts + 1] = string.format("%d%%", math.floor((w:getFuel() or 0) * 100 + 0.5)) end
    return string.format("ok:%d aircraft, fuel %s", #us, table.concat(parts, ", "))
  end
  return "err:unknown intent"
end

function S.cmd(intent, ps)
  local ok, r = pcall(S._cmd, intent, ps)
  if ok then return r end
  return "err:" .. tostring(r)
end

-- Hook entry point: run one command and publish the answer in the "res" mailbox under the caller's sequence number.
function S.run(seq, intent, ps)
  S.put("res", seq, S.cmd(intent, ps))
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

-- Hook entry point, called once per poll. Packs the front of the event queue into the "ev" mailbox; lines stay queued until
-- the Hook acknowledges that exact packet on its next call (at-least-once; the Hook ignores repeats of a sequence number).
S.ev_seq, S.ev_packed = S.ev_seq or 0, S.ev_packed or 0
function S.flush(ack)
  if ack and ack == S.ev_seq and S.ev_packed > 0 then
    for _ = 1, S.ev_packed do table.remove(S.events, 1) end
    S.ev_packed = 0
  end
  if S.ev_packed == 0 and #S.events > 0 then
    local parts, len = {}, 0
    for _, line in ipairs(S.events) do
      local l = line:gsub("%^", "_")
      if len + #l + 1 > NF * 4 - 1 then break end
      parts[#parts + 1] = l; len = len + #l + 1
    end
    if #parts == 0 then parts[1] = S.events[1]:gsub("%^", "_"):sub(1, NF * 4 - 2) end     -- oversized line: truncate, never wedge the queue
    S.ev_seq = S.ev_seq + 1; S.ev_packed = #parts
    S.put("ev", S.ev_seq, table.concat(parts, "^"))
  end
end

function S.drain()
  local out = table.concat(S.events, "\n")
  S.events = {}
  return out
end

trigger.action.setUserFlag("skibo_ready", 5)          -- the Hook checks this to know the module really loaded
return "skibodcs mission module " .. S.version
