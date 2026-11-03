dofile(LockOn_Options.script_path.."command_defs.lua")
dofile(LockOn_Options.script_path.."devices.lua")
local t_start, t_stop, dt = 0.0, 0.0, 0.2
start_sequence_full, stop_sequence_full = {}, {}
function push_command(sequence, run_t, command)
	sequence[#sequence + 1] = command
	sequence[#sequence]["time"] = run_t
end
function push_start_command(delta_t, command) t_start = t_start + delta_t; push_command(start_sequence_full, t_start, command) end
function push_stop_command(delta_t, command) t_stop = t_stop + delta_t; push_command(stop_sequence_full, t_stop, command) end
local count = 0
local function counter() count = count + 1; return count end
count = -1
M_AD_THROTTLE_SET_TO_IDLE = counter()
M_AD_THROTTLE_AT_IDLE = counter()
alert_messages = {}
alert_messages[M_AD_THROTTLE_SET_TO_IDLE] = { message = _("THROTTLE - TO IDLE") }
alert_messages[M_AD_THROTTLE_AT_IDLE] = { message = _("THROTTLE MUST BE AT IDLE") }

push_start_command(2.0, {message = _("AUTOSTART SEQUENCE IS RUNNING")})
push_start_command(dt,  {message = _("- GEAR HANDLE - DN")})
push_start_command(dt,  {device = devices.DEV_A, action = a_commands.One, value = 0.0})
push_start_command(dt,  {message = _("- HOOK SWITCH - UP")})
push_start_command(dt,  {device = devices.DEV_B, action = b_commands.Beta, value = 1.0})
push_start_command(dt,  {message = _("- THROTTLE - IDLE"), check_condition = M_AD_THROTTLE_SET_TO_IDLE})
push_start_command(1.0, {check_condition = M_AD_THROTTLE_AT_IDLE})
for i = 1, 3 do push_start_command(0.5, {device = devices.DEV_B, action = b_commands.Alpha, value = 0.1 * i}) end
push_start_command(3.0, {message = _("AUTOSTART COMPLETE")})
push_stop_command(2.0, {message = _("AUTOSTOP SEQUENCE IS RUNNING")})
push_stop_command(dt,  {device = devices.DEV_A, action = a_commands.One, value = 1.0})
push_stop_command(3.0, {message = _("AUTOSTOP COMPLETE")})
