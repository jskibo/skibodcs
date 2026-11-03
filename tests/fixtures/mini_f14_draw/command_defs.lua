local count = 3000
local function counter() count = count + 1; return count end
Keys = { Engine_Start = 311, Engine_Stop = 312 }
device_commands = { GEAR = counter(), GEAR_EMERG = counter(), RESET = counter() }
