start_command = 3000
local count = 0
local function counter() count = count + 1; return count end
count = start_command
a_commands = { One = counter(); Two = counter(); }
count = start_command
b_commands = { Alpha = counter(); Beta = counter(); Beta_ITER = counter(); }
