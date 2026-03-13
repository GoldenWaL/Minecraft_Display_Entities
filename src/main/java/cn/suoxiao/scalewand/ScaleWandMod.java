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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public class ScaleWandMod implements ModInitializer {
    private static final Map<UUID, Selection> SELECTIONS = new ConcurrentHashMap<>();
    private static final Map<UUID, ClipboardSnapshot> CLIPBOARDS = new ConcurrentHashMap<>();
    private static final SimpleCommandExceptionType NO_SELECTION =
            new SimpleCommandExceptionType(Text.literal("Select two points with a wooden hoe first."));
    private static final SimpleCommandExceptionType NO_CLIPBOARD =
            new SimpleCommandExceptionType(Text.literal("Clipboard is empty, run /copy first."));

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
            player.sendMessage(Text.literal("[Selection] Pos1: " + formatPos(pos)), true);
            return ActionResult.SUCCESS;
        });

        UseBlockCallback.EVENT.register((player, world, hand, hitResult) -> {
            if (!shouldHandleWand(player, world, hand)) {
                return ActionResult.PASS;
            }
            BlockPos pos = hitResult.getBlockPos();
            Selection selection = SELECTIONS.computeIfAbsent(player.getUuid(), ignored -> new Selection());
            selection.setPos2(pos.toImmutable());
            player.sendMessage(Text.literal("[Selection] Pos2: " + formatPos(pos)), true);
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
        final int copiedTotal = total;
        source.sendFeedback(() -> Text.literal("Copied " + copiedTotal + " block states (including air)."), false);
        source.sendFeedback(() -> Text.literal("Copy origin: " + formatPos(copyOrigin)), false);
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

        Map<BlockPos, BlockState> nonAirBlocks = new HashMap<>();
        for (ClipboardBlock block : snapshot.blocks()) {
            if (!block.state().isAir()) {
                nonAirBlocks.put(new BlockPos(block.dx(), block.dy(), block.dz()), block.state());
            }
        }

        int nonAirCount = nonAirBlocks.size();
        List<MergedCuboid> cuboids = mergeCuboids(nonAirBlocks);
        int spawned = 0;

        for (MergedCuboid cuboid : cuboids) {
            DisplayEntity.BlockDisplayEntity display = EntityType.BLOCK_DISPLAY.create(world);
            if (display == null) {
                continue;
            }

            double x = pasteOrigin.getX() + cuboid.x() * scale;
            double y = pasteOrigin.getY() + cuboid.y() * scale;
            double z = pasteOrigin.getZ() + cuboid.z() * scale;

            display.refreshPositionAndAngles(x, y, z, 0.0f, 0.0f);
            display.setBlockState(cuboid.state());
            display.setTransformation(new AffineTransformation(
                    new Vector3f(0.0f, 0.0f, 0.0f),
                    new Quaternionf(),
                    new Vector3f(f * cuboid.sizeX(), f * cuboid.sizeY(), f * cuboid.sizeZ()),
                    new Quaternionf()
            ));

            world.spawnEntity(display);
            spawned++;
        }

        final int pastedTotal = spawned;
        final int rawNonAirTotal = nonAirCount;
        final int mergedTotal = cuboids.size();
        source.sendFeedback(() -> Text.literal(
                "Pasted " + pastedTotal + " display entities from " + rawNonAirTotal
                        + " blocks (merged to " + mergedTotal + "), scale=" + scale
                        + ", origin=" + formatPos(pasteOrigin)
        ), false);
        return spawned;
    }

    private static List<MergedCuboid> mergeCuboids(Map<BlockPos, BlockState> blocks) {
        Map<BlockPos, BlockState> remaining = new HashMap<>(blocks);
        List<MergedCuboid> result = new ArrayList<>();

        while (!remaining.isEmpty()) {
            Map.Entry<BlockPos, BlockState> seed = remaining.entrySet().iterator().next();
            BlockPos origin = seed.getKey();
            BlockState state = seed.getValue();

            int x0 = origin.getX();
            int y0 = origin.getY();
            int z0 = origin.getZ();

            int x1 = x0;
            while (sameState(remaining, x1 + 1, y0, z0, state)) {
                x1++;
            }

            int z1 = z0;
            while (canExpandZ(remaining, state, x0, x1, y0, z1 + 1)) {
                z1++;
            }

            int y1 = y0;
            while (canExpandY(remaining, state, x0, x1, y1 + 1, z0, z1)) {
                y1++;
            }

            for (int y = y0; y <= y1; y++) {
                for (int z = z0; z <= z1; z++) {
                    for (int x = x0; x <= x1; x++) {
                        remaining.remove(new BlockPos(x, y, z));
                    }
                }
            }

            result.add(new MergedCuboid(
                    x0,
                    y0,
                    z0,
                    x1 - x0 + 1,
                    y1 - y0 + 1,
                    z1 - z0 + 1,
                    state
            ));
        }

        return result;
    }

    private static boolean canExpandZ(Map<BlockPos, BlockState> blocks,
                                      BlockState state,
                                      int x0,
                                      int x1,
                                      int y,
                                      int z) {
        for (int x = x0; x <= x1; x++) {
            if (!sameState(blocks, x, y, z, state)) {
                return false;
            }
        }
        return true;
    }

    private static boolean canExpandY(Map<BlockPos, BlockState> blocks,
                                      BlockState state,
                                      int x0,
                                      int x1,
                                      int y,
                                      int z0,
                                      int z1) {
        for (int z = z0; z <= z1; z++) {
            for (int x = x0; x <= x1; x++) {
                if (!sameState(blocks, x, y, z, state)) {
                    return false;
                }
            }
        }
        return true;
    }

    private static boolean sameState(Map<BlockPos, BlockState> blocks,
                                     int x,
                                     int y,
                                     int z,
                                     BlockState expected) {
        BlockState state = blocks.get(new BlockPos(x, y, z));
        return state != null && state.equals(expected);
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

    private record MergedCuboid(int x, int y, int z, int sizeX, int sizeY, int sizeZ, BlockState state) {
    }
}