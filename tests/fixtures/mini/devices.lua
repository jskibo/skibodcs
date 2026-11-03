local count = 0
local function counter() count = count + 1; return count end
devices = {}
devices["DEV_A"] = counter()
devices["DEV_B"] = counter()
