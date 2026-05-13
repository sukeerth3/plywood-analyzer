/*
 * Plywood Cutting Calculator
 * AI-generated from COM S 5130 assignment prompt using Claude (claude-sonnet-4-20250514)
 *
 * Takes plywood sheet dimensions (L x W) and desired cut dimensions (l x w),
 * computes the maximum number of smaller pieces that can be cut,
 * and renders a text-based visualization of the cut layout.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_BOARD_DIM 10000
#define VIS_MAX_WIDTH 80
#define VIS_MAX_HEIGHT 40

struct Dimensions {
    int length;
    int width;
};

struct CutResult {
    int pieces_normal;
    int pieces_rotated;
    int max_pieces;
    int best_rows;
    int best_cols;
    int rotated;
};

int validate_dimensions(int length, int width) {
    if (length <= 0 || width <= 0) {
        fprintf(stderr, "Error: dimensions must be positive integers.\n");
        return 0;
    }
    if (length > MAX_BOARD_DIM || width > MAX_BOARD_DIM) {
        fprintf(stderr, "Error: dimensions exceed maximum (%d).\n", MAX_BOARD_DIM);
        return 0;
    }
    return 1;
}

int get_input(struct Dimensions *board, struct Dimensions *cut) {
    printf("Enter board length (L): ");
    if (scanf("%d", &board->length) != 1) {
        fprintf(stderr, "Error: invalid input for board length.\n");
        return 0;
    }

    printf("Enter board width (W): ");
    if (scanf("%d", &board->width) != 1) {
        fprintf(stderr, "Error: invalid input for board width.\n");
        return 0;
    }

    printf("Enter cut piece length (l): ");
    if (scanf("%d", &cut->length) != 1) {
        fprintf(stderr, "Error: invalid input for cut length.\n");
        return 0;
    }

    printf("Enter cut piece width (w): ");
    if (scanf("%d", &cut->width) != 1) {
        fprintf(stderr, "Error: invalid input for cut width.\n");
        return 0;
    }

    if (!validate_dimensions(board->length, board->width)) return 0;
    if (!validate_dimensions(cut->length, cut->width)) return 0;

    return 1;
}

struct CutResult calculate_cuts(struct Dimensions board, struct Dimensions cut) {
    struct CutResult result;
    memset(&result, 0, sizeof(result));

    // Normal orientation: rows along length, cols along width
    int rows_normal = board.length / cut.length;
    int cols_normal = board.width / cut.width;
    result.pieces_normal = rows_normal * cols_normal;

    // Rotated orientation: swap cut dimensions
    int rows_rotated = board.length / cut.width;
    int cols_rotated = board.width / cut.length;
    result.pieces_rotated = rows_rotated * cols_rotated;

    if (result.pieces_normal >= result.pieces_rotated) {
        result.max_pieces = result.pieces_normal;
        result.best_rows = rows_normal;
        result.best_cols = cols_normal;
        result.rotated = 0;
    } else {
        result.max_pieces = result.pieces_rotated;
        result.best_rows = rows_rotated;
        result.best_cols = cols_rotated;
        result.rotated = 1;
    }

    return result;
}

void print_result(struct CutResult result, struct Dimensions board, struct Dimensions cut) {
    printf("\n--- Cut Results ---\n");
    printf("Board: %d x %d\n", board.length, board.width);
    printf("Cut piece: %d x %d\n", cut.length, cut.width);
    printf("Normal orientation: %d pieces (%d rows x %d cols)\n",
           result.pieces_normal,
           board.length / cut.length,
           board.width / cut.width);

    if (cut.length != cut.width) {
        printf("Rotated orientation: %d pieces (%d rows x %d cols)\n",
               result.pieces_rotated,
               board.length / cut.width,
               board.width / cut.length);
    }

    printf("\nBest: %d pieces", result.max_pieces);
    if (result.rotated) {
        printf(" (rotated)");
    }
    printf("\n");

    // Waste calculation
    int total_area = board.length * board.width;
    int used_area = result.max_pieces * cut.length * cut.width;
    int waste_area = total_area - used_area;
    double waste_pct = (double)waste_area / total_area * 100.0;

    printf("Waste: %d sq units (%.1f%%)\n", waste_area, waste_pct);
}

void render_visualization(struct CutResult result, struct Dimensions board, struct Dimensions cut) {
    printf("\n--- Cut Layout ---\n");

    if (result.max_pieces == 0) {
        printf("No pieces can be cut from this board.\n");
        return;
    }

    int piece_l = result.rotated ? cut.width : cut.length;
    int piece_w = result.rotated ? cut.length : cut.width;

    // Scale to fit terminal
    double scale_x = 1.0, scale_y = 1.0;
    int vis_width = board.width;
    int vis_height = board.length;

    if (vis_width > VIS_MAX_WIDTH) {
        scale_x = (double)VIS_MAX_WIDTH / board.width;
        vis_width = VIS_MAX_WIDTH;
    }
    if (vis_height > VIS_MAX_HEIGHT) {
        scale_y = (double)VIS_MAX_HEIGHT / board.length;
        vis_height = VIS_MAX_HEIGHT;
    }

    // Allocate grid
    char *grid = (char *)malloc(vis_height * vis_width * sizeof(char));
    if (!grid) {
        fprintf(stderr, "Error: memory allocation failed.\n");
        return;
    }

    // Fill background with dots (waste)
    memset(grid, '.', vis_height * vis_width);

    // Fill cut pieces with block chars
    int piece_count = 0;
    for (int r = 0; r < result.best_rows; r++) {
        for (int c = 0; c < result.best_cols; c++) {
            int start_y = (int)(r * piece_l * scale_y);
            int end_y = (int)((r + 1) * piece_l * scale_y);
            int start_x = (int)(c * piece_w * scale_x);
            int end_x = (int)((c + 1) * piece_w * scale_x);

            if (end_y > vis_height) end_y = vis_height;
            if (end_x > vis_width) end_x = vis_width;

            char fill = 'A' + (piece_count % 26);
            piece_count++;

            for (int y = start_y; y < end_y; y++) {
                for (int x = start_x; x < end_x; x++) {
                    // Draw borders between pieces
                    if (y == start_y || x == start_x) {
                        grid[y * vis_width + x] = '+';
                    } else {
                        grid[y * vis_width + x] = fill;
                    }
                }
            }
        }
    }

    // Print top border
    printf("+");
    for (int x = 0; x < vis_width; x++) printf("-");
    printf("+\n");

    // Print grid
    for (int y = 0; y < vis_height; y++) {
        printf("|");
        for (int x = 0; x < vis_width; x++) {
            printf("%c", grid[y * vis_width + x]);
        }
        printf("|\n");
    }

    // Print bottom border
    printf("+");
    for (int x = 0; x < vis_width; x++) printf("-");
    printf("+\n");

    free(grid);
}

int main(int argc, char *argv[]) {
    struct Dimensions board, cut;

    if (argc == 5) {
        // Command-line mode for fuzzing/testing
        board.length = atoi(argv[1]);
        board.width = atoi(argv[2]);
        cut.length = atoi(argv[3]);
        cut.width = atoi(argv[4]);

        if (!validate_dimensions(board.length, board.width) ||
            !validate_dimensions(cut.length, cut.width)) {
            return 1;
        }
    } else {
        // Interactive mode
        if (!get_input(&board, &cut)) {
            return 1;
        }
    }

    struct CutResult result = calculate_cuts(board, cut);
    print_result(result, board, cut);
    render_visualization(result, board, cut);

    return 0;
}
