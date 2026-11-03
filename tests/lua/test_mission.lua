package.path = "tests/lua/?.lua;" .. package.path
local M = require("dcs_mocks")
local eq = M.eq

local function load_module() M.reset(); dofile("dcs_hook/skibodcs_mission.lua"); return SKIBO end

-- flight: player (id 1) + two wingmen (2,3); hostile bandit north 20nm; ground target
local function scenario()
  local S = load_module()
  local p  = M.unit{ id = 1, player = "Skibo", fuel = 0.9 }
  local w1 = M.unit{ id = 2, fuel = 0.8 }
  local w2 = M.unit{ id = 3, fuel = 0.55 }
  M.add(2, 0, M.group{ p, w1, w2 })
  local bandit = M.unit{ id = 50, side = 1, type = "MiG-29S", x = 20 * 1852, z = 0, cat = 0 }
  local far    = M.unit{ id = 51, side = 1, type = "Su-27", x = 90 * 1852, z = 0, cat = 0 }
  M.add(1, 0, M.group{ far, bandit })
  local sam = M.unit{ id = 60, side = 1, type = "Kub", cat = 2 }
  M.add(1, 2, M.group{ sam })
  return S, p, w1, w2
end

-- helper: 4-ship (player + 3 AI) so wingman / element / flight selection can be tested
local function four_ship()
  local S = load_module()
  local p  = M.unit{ id = 1, player = "Skibo", fuel = 0.9 }
  local w2 = M.unit{ id = 2, fuel = 0.8 }
  local w3 = M.unit{ id = 3, fuel = 0.7 }
  local w4 = M.unit{ id = 4, fuel = 0.6 }
  M.add(2, 0, M.group({ p, w2, w3, w4 }, 777))
  M.add(1, 0, M.group{ M.unit{ id = 50, side = 1, type = "MiG-29S", x = 20 * 1852, z = 0, cat = 0 } })
  M.add(1, 2, M.group{ M.unit{ id = 60, side = 1, type = "Kub", cat = 2 } })
  return S, p, w2, w3, w4
end

-- weapons free / hold set ROE on both wingmen, never on the player
do
  local S, p, w1, w2 = scenario()
  eq(S.cmd("weapons_free", ""), "ok:weapons free")
  eq(#w1.ctl.options, 1); eq(#w2.ctl.options, 1); eq(#p.ctl.options, 0, "player untouched")
  eq(w1.ctl.options[1][2], 0)
  eq(S.cmd("weapons_hold", ""), "ok:weapons hold")
  eq(w1.ctl.options[2][2], 4)
end

-- who: wingman = #2 only, element = #3 and #4, "3" = third ship, flight = everyone
do
  local S, _, w2, w3, w4 = four_ship()
  eq(S.cmd("weapons_free", "who=wingman"), "ok:weapons free")
  eq(#w2.ctl.options, 1); eq(#w3.ctl.options, 0); eq(#w4.ctl.options, 0)
  eq(S.cmd("weapons_hold", "who=element"), "ok:weapons hold")
  eq(#w3.ctl.options, 1); eq(#w4.ctl.options, 1); eq(#w2.ctl.options, 1)
  eq(S.cmd("roe", "who=3;level=return_fire"), "ok:return fire")
  eq(#w3.ctl.options, 2); eq(w3.ctl.options[2][2], 3); eq(#w4.ctl.options, 1)
  eq(S.cmd("weapons_free", "who=flight"), "ok:weapons free")
  eq(#w2.ctl.options, 2); eq(#w3.ctl.options, 3); eq(#w4.ctl.options, 2)
  eq(S.cmd("weapons_free", "who=9"), "err:no such flight member")
end

-- radar / ecm / reaction / formation use MOOSE-documented option ids and values
do
  local S, _, w2 = four_ship()
  eq(S.cmd("radar", "who=wingman;level=off"), "ok:radar off");              eq(w2.ctl.options[1][1], 2); eq(w2.ctl.options[1][2], 0)
  eq(S.cmd("radar", "who=wingman;level=continuous"), "ok:radar continuous"); eq(w2.ctl.options[2][2], 3)
  eq(S.cmd("ecm", "who=wingman;level=always"), "ok:ecm always");            eq(w2.ctl.options[3][1], 3); eq(w2.ctl.options[3][2], 3)
  eq(S.cmd("reaction", "who=wingman;level=evade"), "ok:reaction evade");    eq(w2.ctl.options[4][1], 1); eq(w2.ctl.options[4][2], 2)
  eq(S.cmd("formation", "who=wingman;shape=wedge;spacing=close"), "ok:wedge close"); eq(w2.ctl.options[5][1], 4); eq(w2.ctl.options[5][2], 196609)
  eq(S.cmd("formation", "who=wingman;shape=echelon_left"), "ok:echelon left open");   eq(w2.ctl.options[6][2], 327682)
  assert(S.cmd("formation", "who=wingman;shape=vic;spacing=group"):match("^err:unknown formation"), "vic has no group spacing")
  assert(S.cmd("radar", "who=wingman;level=banana"):match("^err:unknown radar level"))
end

-- engage_my_target: air target -> EngageUnit, ground -> AttackUnit, missing -> err
do
  local S, _, w1 = scenario()
  eq(S.cmd("engage_my_target", "target_id=50"), "ok:engaging MiG-29S")
  eq(w1.ctl.tasks[1].id, "EngageUnit"); eq(w1.ctl.tasks[1].params.unitId, 50)
  eq(S.cmd("engage_my_target", "target_id=60"), "ok:engaging Kub")
  eq(w1.ctl.tasks[2].id, "AttackUnit")
  eq(S.cmd("engage_my_target", "target_id=999"), "err:target not found")
  eq(S.cmd("engage_my_target", ""), "err:no target locked")
end

-- engage by category, cover_me, rejoin
do
  local S, _, w2 = four_ship()
  eq(S.cmd("engage_bandits", "who=wingman"), "ok:engage bandits")
  eq(w2.ctl.tasks[1].id, "EngageTargets"); eq(w2.ctl.tasks[1].params.targetTypes[1], "Air")
  S.cmd("engage_ground", "who=wingman"); eq(w2.ctl.tasks[2].params.targetTypes[1], "Ground Units")
  S.cmd("engage_sead", "who=wingman");   eq(w2.ctl.tasks[3].params.targetTypes[1], "Air Defence")
  eq(S.cmd("cover_me", "who=wingman"), "ok:covering you")
  eq(w2.ctl.tasks[4].id, "Escort"); eq(w2.ctl.tasks[4].params.groupId, 777)
  eq(S.cmd("rejoin", "who=wingman"), "ok:rejoining")
  eq(w2.ctl.resets, 1); eq(w2.ctl.tasks[5].id, "Follow"); eq(w2.ctl.tasks[5].params.groupId, 777)
end

-- engage_nearest picks the 20 nm bandit, not the 90 nm one
do
  local S, _, w1 = scenario()
  eq(S.cmd("engage_nearest", ""), "ok:engaging nearest, 20 miles")
  eq(w1.ctl.tasks[1].params.unitId, 50)
end

-- status
do
  local S = scenario()
  eq(S.cmd("status", ""), "ok:2 aircraft, fuel 80%, 55%")
  local S2 = four_ship()
  eq(S2.cmd("status", "who=element"), "ok:2 aircraft, fuel 70%, 60%")
end

-- unimplemented intents never claim success
do
  local S, _, w1 = scenario()
  for _, i in ipairs{ "rtb", "cleared_hot", "break_left", "break_right" } do
    local r = S.cmd(i, "")
    assert(r:match("^err:not implemented"), i .. " -> " .. r)
  end
  eq(#w1.ctl.tasks, 0, "no task pushed")
end

-- no wingman / no player / errors inside DCS calls are contained
do
  M.reset(); dofile("dcs_hook/skibodcs_mission.lua")
  eq(SKIBO.cmd("weapons_free", ""), "err:no player unit found")
  M.add(2, 0, M.group{ M.unit{ id = 1, player = "Skibo" } })
  eq(SKIBO.cmd("weapons_free", ""), "err:no wingman")
  M.reset(); dofile("dcs_hook/skibodcs_mission.lua")
  M.add(2, 0, M.group{ M.unit{ id = 1, player = "Skibo" }, M.unit{ id = 2, boom = true } })
  assert(SKIBO.cmd("weapons_free", ""):match("^err:"), "exceptions become err:")
end

-- events buffer + drain
do
  local S = load_module()
  eq(#world.handlers, 1, "handler registered once")
  dofile("dcs_hook/skibodcs_mission.lua")                    -- reload must not double-register
  eq(#world.handlers, 1)
  local sam = M.unit{ id = 60, name = "sam_site_1-1", group = "sam_site_1", type = "Kub 2P25 ln", side = 1 }
  world.handlers[1]:onEvent{ id = world.event.S_EVENT_DEAD, initiator = sam }
  world.handlers[1]:onEvent{ id = 9999, initiator = sam }    -- ignored kind
  eq(S.drain(), "dead|sam_site_1-1|sam_site_1|Kub 2P25 ln|1|123")
  eq(S.drain(), "")
end

print("MISSION LUA OK")
