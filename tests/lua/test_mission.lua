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

-- unknown intents never claim success
do
  local S, _, w1 = scenario()
  local r = S.cmd("barrel_roll", "")
  assert(r:match("^err:not implemented"), r)
  eq(#w1.ctl.tasks, 0, "no task pushed")
end

-- rtb: each wingman gets a route to the nearest friendly AIRDROME (not a helipad / ship)
do
  local S, p, w1, w2 = scenario()
  eq(S.cmd("rtb", ""), "err:no friendly airfield found")
  coalition.getAirbases = coalition.getAirbases
  M.airbases[2] = { M.airbase{ name = "Helipad", id = 9, x = 1000, z = 0, cat = 1 },
                    M.airbase{ name = "Batumi", id = 5, x = -30 * 1852, z = 0, cat = 0 },
                    M.airbase{ name = "Kobuleti", id = 6, x = -80 * 1852, z = 0, cat = 0 } }
  eq(S.cmd("rtb", ""), "ok:returning to Batumi")
  local pts = w1.ctl.set.params.route.points
  eq(#pts, 2); eq(pts[2].type, "Land"); eq(pts[2].action, "Landing"); eq(pts[2].airdromeId, 5)
  assert(w2.ctl.set, "second wingman tasked too"); eq(p.ctl.set, nil, "player untouched")
  eq(S.cmd("rtb", "who=2"), "ok:returning to Batumi")
end

-- break left / right: a 90 degree turn point 10 nm out, relative to each wingman's own heading
do
  local S, _, w1 = scenario()
  eq(S.cmd("break_right", ""), "ok:breaking right")
  local q = w1.ctl.set.params.route.points[2]
  assert(math.abs(q.x - 0) < 1 and math.abs(q.y - 18520) < 1, "heading north, break right = east: x=" .. q.x .. " y=" .. q.y)
  eq(S.cmd("break_left", ""), "ok:breaking left")
  q = w1.ctl.set.params.route.points[2]
  assert(math.abs(q.y + 18520) < 1, "break left = west")
end

-- cleared hot: explicit lock wins; otherwise nearest hostile ground unit inside the forward arc; never behind
do
  local S, _, w1 = scenario()
  eq(S.cmd("cleared_hot", "target_id=60"), "ok:attacking Kub")
  eq(w1.ctl.tasks[1].id, "AttackUnit"); eq(w1.ctl.tasks[1].params.unitId, 60)
  local S2, _, v1 = scenario()
  M.add(1, 2, M.group{ M.unit{ id = 61, side = 1, type = "T-72B", x = 10 * 1852, z = 0, cat = 2 },
                       M.unit{ id = 62, side = 1, type = "BMP-2", x = -5 * 1852, z = 0, cat = 2 } })
  eq(S2.cmd("cleared_hot", ""), "ok:attacking Kub")                  -- sam at 0 m is nearest
  M.reset(); S2 = load_module()
  M.add(2, 0, M.group{ M.unit{ id = 1, player = "Skibo" }, M.unit{ id = 2 } })
  M.add(1, 2, M.group{ M.unit{ id = 62, side = 1, type = "BMP-2", x = -5 * 1852, z = 0, cat = 2 } })
  eq(S2.cmd("cleared_hot", ""), "err:no ground target in front of you")
  M.add(1, 2, M.group{ M.unit{ id = 61, side = 1, type = "T-72B", x = 10 * 1852, z = 0, cat = 2 } })
  eq(S2.cmd("cleared_hot", ""), "ok:attacking T-72B")
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

-- the module must load even when `AI` is not defined yet (real log: inject failed at onSimulationStart), then work once it is
do
  M.reset()
  local saved = AI; AI = nil
  local ok, err = pcall(dofile, "dcs_hook/skibodcs_mission.lua")
  assert(ok, "module must load without AI: " .. tostring(err))
  local p = M.unit{ id = 1, player = "Skibo" }; local w = M.unit{ id = 2 }
  M.add(2, 0, M.group{ p, w })
  assert(SKIBO.cmd("weapons_free", ""):match("^err:AI options not available"), "no AI yet -> honest error")
  eq(#w.ctl.options, 0)
  AI = saved
  eq(SKIBO.cmd("weapons_free", ""), "ok:weapons free")                         -- same module instance, AI now present
  eq(#w.ctl.options, 1)
  assert(SKIBO.cmd("status", ""):match("^ok:"), "intents that do not need AI never depended on it")
end

-- flag mailbox: text -> 4 chars per flag -> text, with the sequence number committed last
local function decode(prefix)
  local out = {}
  for i = 1, SKIBO.NF do
    local n = M.flags["skibo_" .. prefix .. "_" .. i]
    for _, div in ipairs({ 1000000, 10000, 100, 1 }) do
      local c = math.floor(n / div) % 100
      if c == 99 then return M.flags["skibo_" .. prefix .. "_0"], table.concat(out) end
      out[#out + 1] = string.char(c + 32)
    end
  end
  return M.flags["skibo_" .. prefix .. "_0"], table.concat(out)
end
do
  local S = load_module()
  eq(M.flags["skibo_ready"], 5, "module announces itself through a flag")
  for _, txt in ipairs{ "", "ok:weapons free", "a", "abcd", "abc", string.rep("x", 200), "ok:engaging T-72B, 12 miles | ~^ \n" } do
    S.put("res", 7, txt)
    local seq, got = decode("res")
    local want = txt:gsub("[^\32-\126]", "?"):sub(1, S.NF * 4 - 1)
    eq(seq, 7); eq(got, want, "round trip of [" .. txt .. "]")
  end
  for i = 1, S.NF do assert(M.flags["skibo_res_" .. i] < 2147483647, "every flag stays inside int32") end
  -- S.run: command result lands in the mailbox under the caller's sequence number
  local p1 = M.unit{ id = 1, player = "Skibo" }; local w1 = M.unit{ id = 2 }
  M.add(2, 0, M.group{ p1, w1 })
  S.run(41, "weapons_free", "")
  local seq, got = decode("res"); eq(seq, 41); eq(got, "ok:weapons free")
  S.run(42, "barrel_roll", "")
  seq, got = decode("res"); eq(seq, 42); assert(got:match("^err:not implemented"), got)
end

-- event mailbox: at-least-once with an explicit ack; oversized lines never wedge the queue; '^' (the line separator) is sanitised
do
  local S = load_module()
  S.events = { "dead|sa6_site_1-1|sa6_site_1|Kub 2P25 ln|1|10", "dead|sa6_site_1-2|sa6_site_1|Kub 2P25 ln|1|11",
               "dead|sa6_site_1-3|sa6_site_1|Kub 2P25 ln|1|12", "dead|sa6_site_1-4|sa6_site_1|Kub 2P25 ln|1|13" }
  S.flush()
  local seq, text = decode("ev"); eq(seq, 1)
  local n = select(2, text:gsub("dead", ""))
  assert(n >= 1 and n < 4, "a packet carries as many whole lines as fit (" .. n .. ")")
  S.flush()                                               -- no ack: the same lines must stay queued, packet number unchanged
  eq(S.ev_seq, 1); eq(#S.events, 4)
  S.flush(1)                                              -- ack: those lines go, the next packet is packed
  eq(S.ev_seq, 2); eq(#S.events, 4 - n)
  local _, t2 = decode("ev"); assert(t2:find("dead|sa6_site_1-" .. (n + 1), 1, true), t2)
  S.flush(2); S.flush(S.ev_seq)
  while #S.events > 0 do S.flush(S.ev_seq) end            -- drains completely
  S.events = { "dead|" .. string.rep("z", 300) .. "|g|t|1|1", "kill|u^x|g|t|1|2" }
  S.ev_packed = 0
  S.flush(); local s3, t3 = decode("ev")
  assert(#t3 > 0 and #t3 <= S.NF * 4 - 1, "oversized line truncated")
  S.flush(S.ev_seq); S.flush()
  local _, t4 = decode("ev"); eq(t4, "kill|u_x|g|t|1|2", "separator inside a name is replaced")
end

print("MISSION LUA OK")
