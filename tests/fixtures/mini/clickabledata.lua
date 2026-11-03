dofile(LockOn_Options.script_path.."clickable_defs.lua")
dofile(LockOn_Options.script_path.."command_defs.lua")
dofile(LockOn_Options.script_path.."devices.lua")
dofile(LockOn_Options.script_path.."config.lua")
local gettext = require("i_18n")
_ = gettext.translate
elements = {}
elements["SW-1"] = default_2_position_tumb(_("Test Switch, UP/DN"), devices.DEV_B, b_commands.Beta, 77)
elements["BTN-1"] = default_button(_("Test Button"), devices.DEV_A, a_commands.One, 12)
elements["TRI-1"] = springloaded_3_pos_tumb(_("Tri Switch, A/B/C"), devices.DEV_A, a_commands.One, a_commands.Two, 9)
elements["KNOB-1"] = multiposition_switch(_("Knob"), devices.DEV_B, b_commands.Alpha, 30, 4, 0.1, NOT_INVERSED, 0.0, anim_speed_default * 0.1, NOT_CYCLED)
elements["CUSTOM-1"] = {
	class = {class_type.TUMB, class_type.LEV},
	hint = _("Custom Handle"),
	device = devices.DEV_A,
	action = {a_commands.Two, a_commands.Two},
	arg = {5, 5},
	sound = {{SOUND_SW2}},
}
elements["SW-1"].sound = {{SOUND_SW12_ON, SOUND_SW12_OFF}}
