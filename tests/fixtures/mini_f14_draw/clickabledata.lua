local gettext = require("i_18n")
_ = gettext.translate
dofile(LockOn_Options.script_path.."paths.lua")
dofile(base_script_path.."draw_args.lua")
dofile(base_script_path.."command_defs.lua")
dofile(base_script_path.."devices.lua")
pilot_only = {0}
rio_only = {1}
pilot_and_rio = {0, 1}
function __(text) return _(text) end
function default_2_position_tumb(hint_, device_, command_, arg_, crew_)
	return { class = {class_type.TUMB, class_type.TUMB}, hint = hint_, device = device_, action = {command_, command_},
	         arg = {arg_}, crew_member_access = crew_ or pilot_and_rio }
end
function default_button(hint_, device_, command_, arg_, arg_val_, arg_lim_, crew_)
	return { class = {class_type.BTN}, hint = hint_, device = device_, action = {command_}, arg = {arg_},
	         crew_member_access = crew_ or pilot_and_rio }
end
elements = {}
elements["X1"] = default_2_position_tumb(__("Gear Lever"), devices.GEARHOOK, device_commands.GEAR, cockpit_args.GEAR, pilot_only)
elements["X2"] = default_button(__("Radar Reset"), devices.RADAR, device_commands.RESET, cockpit_args.RESET, nil, nil, rio_only)
elements["X3"] = default_button(__("Shared Button"), devices.RADAR, device_commands.GEAR_EMERG, cockpit_args.SHARED)
