from ten_runtime import AsyncExtension, AsyncTenEnv, Cmd, CmdResult, StatusCode


class JevTurnControlExtension(AsyncExtension):
    """Public-runtime loading probe; turn decisions are not implemented yet."""

    async def on_start(self, ten_env: AsyncTenEnv) -> None:
        ten_env.log_info("JEV_EXTENSION_READY stage=bootstrap_only")

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd) -> None:
        if cmd.get_name() != "jev_ping":
            result = CmdResult.create(StatusCode.ERROR, cmd)
            result.set_property_string("detail", "unsupported command")
        else:
            nonce, error = cmd.get_property_string("nonce")
            result = CmdResult.create(
                StatusCode.ERROR if error else StatusCode.OK, cmd
            )
            result.set_property_string("nonce", nonce)
            result.set_property_string("stage", "bootstrap_only")
        await ten_env.return_result(result)
