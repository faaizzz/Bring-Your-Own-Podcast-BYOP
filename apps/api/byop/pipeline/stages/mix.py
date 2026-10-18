from byop.pipeline.context import RunContext


async def run(ctx: RunContext) -> None:
    """Mix the speech into one audio file (a later story replaces this stub)."""
    await ctx.checkpoint()
    await ctx.log("Not implemented yet: this step is skipped")
    await ctx.progress(1.0)
