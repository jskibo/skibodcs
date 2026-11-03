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

-- weapons free / hold set ROE on both wingmen, never on the player
do
  local S, p, w1, w2 = scenario()
  eq(S.cmd("weapons_free", "", "auto", ""), "ok:weapons free")
  eq(#w1.ctl.options, 1); eq(#w2.ctl.options, 1); eq(#p.ctl.options, 0, "player untouched")
  eq(w1.ctl.options[1][2], 0)
  eq(S.cmd("weapons_hold", "", "auto", ""), "ok:weapons hold")
  eq(w1.ctl.options[2][2], 4)
end

-- engage_my_target: air target -> EngageUnit, ground -> AttackUnit, missing -> err
do
  local S, _, w1 = scenario()
  eq(S.cmd("engage_my_target", "", "auto", "50"), "ok:engaging MiG-29S")
  eq(w1.ctl.tasks[1].id, "EngageUnit"); eq(w1.ctl.tasks[1].params.unitId, 50)
  eq(S.cmd("engage_my_target", "", "auto", "60"), "ok:engaging Kub")
  eq(w1.ctl.tasks[2].id, "AttackUnit")
  eq(S.cmd("engage_my_target", "", "auto", "999"), "err:target not found")
  eq(S.cmd("engage_my_target", "", "auto", ""), "err:no target locked")
end

-- engage_nearest picks the 20 nm bandit, not the 90 nm one
do
  local S, _, w1 = scenario()
  eq(S.cmd("engage_nearest", "", "auto", ""), "ok:engaging nearest, 20 miles")
  eq(w1.ctl.tasks[1].params.unitId, 50)
end

-- status
do
  local S = scenario()
  eq(S.cmd("status", "", "auto", ""), "ok:2 wingman, fuel 80%, 55%")
end

-- unimplemented intents never claim success
do
  local S, _, w1 = scenario()
  for _, i in ipairs{ "formation", "cover_me", "rejoin", "rtb", "cleared_hot", "break_left" } do
    local r = S.cmd(i, "spread", "auto", "")
    assert(r:match("^err:not implemented"), i .. " -> " .. r)
  end
  eq(#w1.ctl.tasks, 0, "no task pushed")
end

-- no wingman / no player / errors inside DCS calls are contained
do
  M.reset(); dofile("dcs_hook/skibodcs_mission.lua")
  eq(SKIBO.cmd("weapons_free", "", "", ""), "err:no player unit found")
  M.add(2, 0, M.group{ M.unit{ id = 1, player = "Skibo" } })
  eq(SKIBO.cmd("weapons_free", "", "", ""), "err:no wingman")
  M.reset(); dofile("dcs_hook/skibodcs_mission.lua")
  M.add(2, 0, M.group{ M.unit{ id = 1, player = "Skibo" }, M.unit{ id = 2, boom = true } })
  assert(SKIBO.cmd("weapons_free", "", "", ""):match("^err:"), "exceptions become err:")
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
