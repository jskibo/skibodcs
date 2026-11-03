local count = 0
local function counter() count = count + 1; return count end
devices = {}
devices["GEARHOOK"] = counter()
devices["RADAR"] = counter()
