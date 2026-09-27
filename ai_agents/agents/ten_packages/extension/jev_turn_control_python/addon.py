from ten_runtime import Addon, TenEnv, register_addon_as_extension

from .extension import JevTurnControlExtension


@register_addon_as_extension("jev_turn_control_python")
class JevTurnControlAddon(Addon):
    def on_create_instance(
        self, ten_env: TenEnv, name: str, context: object
    ) -> None:
        ten_env.on_create_instance_done(JevTurnControlExtension(name), context)
