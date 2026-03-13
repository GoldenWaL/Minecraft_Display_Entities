package cn.suoxiao.scalewand;

import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.DoubleArgumentType;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import com.mojang.brigadier.exceptions.SimpleCommandExceptionType;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.player.AttackBlockCallback;
import net.fabricmc.fabric.api.event.player.UseBlockCallback;
import net.minecraft.block.BlockState;
import net.minecraft.command.CommandRegistryAccess;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.SpawnReason;
import net.minecraft.entity.decoration.DisplayEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.text.Text;
import net.minecraft.util.ActionResult;
import net.minecraft.util.Hand;
import net.minecraft.util.math.AffineTransformation;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.World;
import org.joml.Quaternionf;
import org.joml.Vector3f;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public class ScaleWandMod implements ModInitializer {
    private static final Map<UUID, Selection> SELECTIONS = new ConcurrentHashMap<>();
    private static final Map<UUID, ClipboardSnapshot> CLIPBOARDS = new ConcurrentHashMap<>();
    private static final SimpleCommandExceptionType NO_SELECTION =
            new SimpleCommandExceptionType(Text.literal("请先用木锄选择两个点。"));
    private static final SimpleCommandExceptionType NO_CLIPBOARD =
            new SimpleCommandExceptionType(Text.literal("当前没有复制内容，请先执行 /copy。"));

    @Override
    public void onInitialize() {
        registerWandEvents();
        CommandRegistrationCallback.EVENT.register(this::registerCommands);
    }

    private void registerWandEvents() {
        AttackBlockCallback.EVENT.register((player, world, hand, pos, direction) -> {
            if (!shouldHandleWand(player, world, hand)) {
                return ActionResult.PASS;
            }
            Selection selection = SELECTIONS.computeIfAbsent(player.getUuid(), ignored -> new Selection());
            selection.setPos1(pos.toImmutable());
            player.sendMessage(Text.literal("[选区] 第一选择点: " + formatPos(pos)), true);
            return ActionResult.SUCCESS;
        });

        UseBlockCallback.EVENT.register((player, world, hand, hitResult) -> {
            if (!shouldHandleWand(player, world, hand)) {
                return ActionResult.PASS;
            }
            BlockPos pos = hitResult.getBlockPos();
            Selection selection = SELECTIONS.computeIfAbsent(player.getUuid(), ignored -> new Selection());
            selection.setPos2(pos.toImmutable());
            player.sendMessage(Text.literal("[选区] 第二选择点: " + formatPos(pos)), true);
            return ActionResult.SUCCESS;
        });
    }

    private boolean shouldHandleWand(net.minecraft.entity.player.PlayerEntity player, World world, Hand hand) {
        if (world.isClient() || hand != Hand.MAIN_HAND) {
            return false;
        }
        ItemStack stack = player.getMainHandStack();
        return stack.isOf(Items.WOODEN_HOE);
    }

    private void registerCommands(CommandDispatcher<ServerCommandSource> dispatcher,
                                  CommandRegistryAccess registryAccess,
                                  CommandManager.RegistrationEnvironment environment) {
        dispatcher.register(CommandManager.literal("copy")
                .requires(source -> source.hasPermissionLevel(2))
                .executes(ctx -> runCopy(ctx.getSource())));

        dispatcher.register(CommandManager.literal("paste")
                .requires(source -> source.hasPermissionLevel(2))
                .executes(ctx -> runPaste(ctx.getSource(), 1.0))
                .then(CommandManager.argument("scale", DoubleArgumentType.doubleArg(0.1, 16.0))
                        .executes(ctx -> runPaste(ctx.getSource(), DoubleArgumentType.getDouble(ctx, "scale")))));
    }

    private int runCopy(ServerCommandSource source) throws CommandSyntaxException {
        ServerPlayerEntity player = source.getPlayerOrThrow();
        Selection selection = SELECTIONS.get(player.getUuid());
        if (selection == null || !selection.complete()) {
            throw NO_SELECTION.create();
        }

        BlockPos min = selection.min();
        BlockPos max = selection.max();
        BlockPos copyOrigin = player.getBlockPos();
        ServerWorld world = player.getServerWorld();

        List<ClipboardBlock> blocks = new ArrayList<>();
        int total = 0;
        for (BlockPos pos : BlockPos.iterate(min, max)) {
            total++;
            BlockState state = world.getBlockState(pos);
            BlockPos offset = pos.subtract(copyOrigin);
            blocks.add(new ClipboardBlock(offset.getX(), offset.getY(), offset.getZ(), state));
        }

        CLIPBOARDS.put(player.getUuid(), new ClipboardSnapshot(blocks));
        source.sendFeedback(() -> Text.literal("复制完成: 扫描并保存 " + total + " 个方块状态（含空气）。"), false);
        source.sendFeedback(() -> Text.literal("复制原点(相对): " + formatPos(copyOrigin)), false);
        return blocks.size();
    }

    private int runPaste(ServerCommandSource source, double scale) throws CommandSyntaxException {
        ServerPlayerEntity player = source.getPlayerOrThrow();
        ClipboardSnapshot snapshot = CLIPBOARDS.get(player.getUuid());
        if (snapshot == null || snapshot.blocks().isEmpty()) {
            throw NO_CLIPBOARD.create();
        }

        ServerWorld world = player.getServerWorld();
        BlockPos pasteOrigin = player.getBlockPos();
        float f = (float) scale;
        int spawned = 0;

        for (ClipboardBlock block : snapshot.blocks()) {
            if (block.state().isAir()) {
                continue;
            }

            DisplayEntity.BlockDisplayEntity display = EntityType.BLOCK_DISPLAY.create(world, SpawnReason.COMMAND);
            if (display == null) {
                continue;
            }

            double x = pasteOrigin.getX() + block.dx() * scale;
            double y = pasteOrigin.getY() + block.dy() * scale;
            double z = pasteOrigin.getZ() + block.dz() * scale;

            display.refreshPositionAndAngles(x, y, z, 0.0f, 0.0f);
            display.setBlockState(block.state());
            display.setTransformation(new AffineTransformation(
                    new Vector3f(0.0f, 0.0f, 0.0f),
                    new Quaternionf(),
                    new Vector3f(f, f, f),
                    new Quaternionf()
            ));

            world.spawnEntity(display);
            spawned++;
        }

        source.sendFeedback(() -> Text.literal(
                "粘贴完成: 已生成 " + spawned + " 个展示实体, 缩放倍数=" + scale + ", 粘贴原点=" + formatPos(pasteOrigin)
        ), false);
        return spawned;
    }

    private static String formatPos(BlockPos pos) {
        return "(" + pos.getX() + ", " + pos.getY() + ", " + pos.getZ() + ")";
    }

    private static final class Selection {
        private BlockPos pos1;
        private BlockPos pos2;

        private void setPos1(BlockPos pos1) {
            this.pos1 = pos1;
        }

        private void setPos2(BlockPos pos2) {
            this.pos2 = pos2;
        }

        private boolean complete() {
            return pos1 != null && pos2 != null;
        }

        private BlockPos min() {
            return new BlockPos(
                    Math.min(pos1.getX(), pos2.getX()),
                    Math.min(pos1.getY(), pos2.getY()),
                    Math.min(pos1.getZ(), pos2.getZ())
            );
        }

        private BlockPos max() {
            return new BlockPos(
                    Math.max(pos1.getX(), pos2.getX()),
                    Math.max(pos1.getY(), pos2.getY()),
                    Math.max(pos1.getZ(), pos2.getZ())
            );
        }
    }

    private record ClipboardSnapshot(List<ClipboardBlock> blocks) {
    }

    private record ClipboardBlock(int dx, int dy, int dz, BlockState state) {
    }
}
