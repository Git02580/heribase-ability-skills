# Verify HeriBase Connector

Use the same photos to compare what the organizer saves before and after review, or repeat the installation check in a fresh environment.

## Five-photo workbench check

1. [Download the five sample photos](coin-photo-sample.zip). Unzip the archive and use the five JPEGs.
2. Follow the [Quick start](../README.md#quick-start), then ask your agent to open the Add Coins workbench. To run the same automatic organizer, use the workbench with a signed-in Codex CLI.
3. Upload the five JPEGs, let the organizer finish, then inspect the saved results. If the photos are separate, use the photo editor to confirm the pairs below. Reopen the same task to see what was saved.

**Observed on November 13, 2026:** In both runs, the automatic organizer saved all five original photos and left them as separate sides. On the second run, we manually confirmed the two pairs below, then reopened the task and checked that both pairs and the incomplete record were still there.

| Reference coin | Front | Back | State after review and reopening |
| --- | --- | --- | --- |
| 1860 Indian Head cent | `IMG_1023.jpg` | `IMG_1025.jpg` | Pair confirmed |
| 1883 Liberty Head nickel | `IMG_1024.jpg` | `IMG_1021.jpg` | Pair confirmed |
| 1892 Barber dime | `IMG_1022.jpg` | — | One side missing |

[Run 1: automatic result](sample-automatic-run.json) · [Run 2: automatic result and saved review](sample-review-run.json) · [Museum photo sources](demo-credits.md)

The records include the Connector commit, tool version, and SHA-256 hashes for the download and each photo. The coin names are reference labels from the photo sources. The run used Codex for image grouping. It stopped before HeriBase online identification or saving to an online collection.

## Clean installation check

On November 13, 2026, we used two fresh macOS user directories with Node.js 24 and Python 3.12. One installed from the current GitHub address and the other from the previous address. Both copied all six Skills, returned `ok: true` from the README initialization command, and supplied the full instructions for all six to a fresh Codex session. No HeriBase account was signed in.

[Clean-install report](clean-install-run.json) · [Installation and troubleshooting](installation.md)

## Who publishes HeriBase

[HeriBase](https://www.heribase.com/) is the service behind the Connector. Its separate mobile app is listed on the [App Store](https://apps.apple.com/us/app/heribase-ai-coin-identifier/id6762598274) and [Google Play](https://play.google.com/store/apps/details?id=com.weipaitang.coin). Store ratings and reviews describe the mobile app.
