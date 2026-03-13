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
import net.minecraft.entity.Entity;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.decoration.DisplayEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.registry.RegistryKey;
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
    private static final Map<UUID, List<SpawnedDisplayRef>> LAST_PASTES = new ConcurrentHashMap<>();

    private static final SimpleCommandExceptionType NO_SELECTION =
            new SimpleCommandExceptionType(Text.literal("Select two points with a wooden hoe first."));
    private static final SimpleCommandExceptionType NO_CLIPBOARD =
            new SimpleCommandExceptionType(Text.literal("Clipboard is empty, run /copy first."));
    private static final SimpleCommandExceptionType NO_LAST_PASTE =
            new SimpleCommandExceptionType(Text.literal("No recent paste to undo."));

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

        dispatcher.register(CommandManager.literal("ctrlz")
                .requires(source -> source.hasPermissionLevel(2))
                .executes(ctx -> runCtrlz(ctx.getSource())));
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
        List<SpawnedDisplayRef> spawnedRefs = new ArrayList<>();
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
            spawnedRefs.add(new SpawnedDisplayRef(world.getRegistryKey(), display.getUuid()));
            spawned++;
        }

        LAST_PASTES.put(player.getUuid(), spawnedRefs);

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

    private int runCtrlz(ServerCommandSource source) throws CommandSyntaxException {
        ServerPlayerEntity player = source.getPlayerOrThrow();
        List<SpawnedDisplayRef> refs = LAST_PASTES.remove(player.getUuid());
        if (refs == null || refs.isEmpty()) {
            throw NO_LAST_PASTE.create();
        }

        int removed = 0;
        for (SpawnedDisplayRef ref : refs) {
            ServerWorld targetWorld = source.getServer().getWorld(ref.worldKey());
            if (targetWorld == null) {
                continue;
            }

            Entity entity = targetWorld.getEntity(ref.entityUuid());
            if (entity != null) {
                entity.discard();
                removed++;
            }
        }

        final int removedTotal = removed;
        source.sendFeedback(() -> Text.literal("Undo complete. Removed " + removedTotal + " display entities."), false);
        return removed;
    }

    private static List<MergedCuboid> mergeCuboids(Map<BlockPos, BlockState> blocks) {
        if (blocks.isEmpty()) {
            return List.of();
        }

        int minX = Integer.MAX_VALUE;
        int minY = Integer.MAX_VALUE;
        int minZ = Integer.MAX_VALUE;
        int maxX = Integer.MIN_VALUE;
        int maxY = Integer.MIN_VALUE;
        int maxZ = Integer.MIN_VALUE;

        Map<Long, BlockState> remaining = new HashMap<>(blocks.size() * 2);
        for (Map.Entry<BlockPos, BlockState> entry : blocks.entrySet()) {
            BlockPos pos = entry.getKey();
            remaining.put(pos.asLong(), entry.getValue());

            minX = Math.min(minX, pos.getX());
            minY = Math.min(minY, pos.getY());
            minZ = Math.min(minZ, pos.getZ());
            maxX = Math.max(maxX, pos.getX());
            maxY = Math.max(maxY, pos.getY());
            maxZ = Math.max(maxZ, pos.getZ());
        }

        List<MergedCuboid> result = new ArrayList<>();

        for (int y = minY; y <= maxY; y++) {
            for (int z = minZ; z <= maxZ; z++) {
                for (int x = minX; x <= maxX; x++) {
                    long seedKey = BlockPos.asLong(x, y, z);
                    BlockState state = remaining.get(seedKey);
                    if (state == null) {
                        continue;
                    }

                    int x1 = x;
                    while (sameState(remaining, x1 + 1, y, z, state)) {
                        x1++;
                    }

                    int z1 = z;
                    while (canExpandZ(remaining, state, x, x1, y, z1 + 1)) {
                        z1++;
                    }

                    int y1 = y;
                    while (canExpandY(remaining, state, x, x1, y1 + 1, z, z1)) {
                        y1++;
                    }

                    for (int yy = y; yy <= y1; yy++) {
                        for (int zz = z; zz <= z1; zz++) {
                            for (int xx = x; xx <= x1; xx++) {
                                remaining.remove(BlockPos.asLong(xx, yy, zz));
                            }
                        }
                    }

                    result.add(new MergedCuboid(
                            x,
                            y,
                            z,
                            x1 - x + 1,
                            y1 - y + 1,
                            z1 - z + 1,
                            state
                    ));
                }
            }
        }

        return result;
    }

    private static boolean canExpandZ(Map<Long, BlockState> blocks,
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

    private static boolean canExpandY(Map<Long, BlockState> blocks,
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

    private static boolean sameState(Map<Long, BlockState> blocks,
                                     int x,
                                     int y,
                                     int z,
                                     BlockState expected) {
        BlockState state = blocks.get(BlockPos.asLong(x, y, z));
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

    private record SpawnedDisplayRef(RegistryKey<World> worldKey, UUID entityUuid) {
    }
}