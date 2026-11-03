local gettext = require("i_18n")
_ = gettext.translate
dofile(LockOn_Options.script_path.."command_defs.lua")
dofile(LockOn_Options.script_path.."devices.lua")
function default_2_position_tumb(hint_, device_, command_, arg_, arg_val_)
	return { class = {class_type.TUMB, class_type.TUMB}, hint = hint_, device = device_, action = {command_, command_},
	         arg = {arg_, arg_}, arg_value = arg_val_ or {-1, 1} }
end
function default_button(hint_, device_, command_, arg_)
	return { class = {class_type.BTN, class_type.BTN}, hint = hint_, device = device_, action = {command_, command_}, arg = {arg_, arg_} }
end
elements = {}
-- same device_commands.Button_N name on two devices: only DEVICE:name disambiguates
elements["G"]  = default_2_position_tumb(_("Landing Gear Lever"), devices.CPT_MECH, device_commands.Button_1, 716, {1, -1})
elements["B"]  = default_2_position_tumb(_("Battery Power"), devices.ELEC_INTERFACE, device_commands.Button_1, 246)
elements["ES"] = default_button(_("ENGINE START L"), devices.ELEC_INTERFACE, device_commands.Button_2, 676)
