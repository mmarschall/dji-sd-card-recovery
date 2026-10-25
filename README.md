# DJI SD card video recovery

Scripts used to recover the videos from an SD card image of a DJI O4 Air Unit Pro
(camera model FC8885) after the drone went into water. The card was exFAT, 128 GB,
128 KiB clusters.

The image is only ever read. All output goes to a separate folder.

## What was wrong with the card

- The exFAT file system itself was consistent (`fsck_exfat` OK), but the `DCIM`
  directory was gone. Only macOS Spotlight files remained.
- The card had been mounted on a Mac. Spotlight allocated about 150 clusters at
  the start of the data area and overwrote the beginning of the oldest video there.
- The card was full of videos from several months of use. New recordings were
  written into the gaps between old ones, so most files are heavily fragmented
  (single clusters scattered over up to 9 GB). Short clips were later written into
  single clusters freed by the camera's temporary files.

## How the recovery works

Every DJI MP4 has three tracks: HEVC video (`hvc1`) and two telemetry tracks
(`djmd`, `dbgi`). Each telemetry sample carries a frame counter and a microsecond
timestamp, and the `moov` index at the end of each file lists the exact size and
file offset of every sample.

1. **Scan** the whole image for `ftyp` headers, `moov` indexes and DJI file names
   (`scan2.py`).
2. **Pair** each `moov` with its header via the `mdat` size in the header
   (`pair.py`). Names come from fragments of the camera's media database
   (`names.py`).
3. **Index** every telemetry sample on the card: position, size, counter,
   timestamp (`metaindex.py`).
4. **Anchor** clusters: a telemetry sample with the exact size, the exact offset
   inside its cluster and a timestamp that continues the previous frame
   (+16683 us at 59.94 fps) pins its file cluster to a disk cluster (`chain.py`).
5. **Certain clusters** are anchors plus runs between two anchors whose disk
   distance equals their file distance. These are treated as owned.
6. **Fill the gaps** between anchors from clusters no other file certainly owns.
   When there are more candidates than slots, clusters are chosen one at a time
   in allocation order and judged by decoding the affected frames: a wrong
   cluster makes the HEVC decoder lose sync and leaves flat green or magenta
   areas (`greedy.py`, `plan_v4.py`).
7. **Lost headers**: for clips whose first cluster was overwritten, anchors are
   built backwards from the `moov`, which is always intact (`lost3.py`).
8. **Write** each file with a standard 512-byte DJI header, the reassembled
   `mdat` and the original `moov` (`write_all.py`).
9. **Verify** by a full VideoToolbox decode of every frame (`verify2.sh`).
   VideoToolbox drops frames it cannot decode, which makes it a much stricter
   check than the software decoder. It reported 4 false alarms on one clean clip.

A structural check (valid chain of HEVC NAL lengths per frame) is not enough on
its own. Wrong clusters inside a large slice pass it and only show up when
decoding.

## Run order

```bash
IMG=/path/to/card.img
W=work            # intermediate files
OUT=/path/to/output/DCIM/DJI_001
mkdir -p $W

python3 -I recovery/card.py      $IMG > card.json     # geometry from the boot sector
python3 -I recovery/scan2.py     $IMG $W/scan2.txt
python3 -I recovery/pair.py      $IMG $W/scan2.txt $W/pairs.json
python3 -I recovery/names.py     $W/scan2.txt $W/pairs.json $W/names.json Europe/Paris   # camera time zone
python3 -I recovery/metaindex.py $IMG $W/metaindex.bin
python3 -I recovery/plan_v4.py   $IMG $W/pairs.json $W/metaindex.bin $W/names.json $W/plan_v4 4
python3 -I recovery/write_all.py $IMG $W/plan_v4.chains.pkl $OUT
python3 -I recovery/lost3.py     $IMG $W/pairs.json $W/metaindex.bin $W/names.json $W/plan_v4 $W/lost3
python3 -I recovery/write_all.py $IMG $W/lost3.chains.pkl $OUT
recovery/verify2.sh $W $OUT/*.MP4
```

The scan and the index each read the full image once (about 30 to 45 minutes for
128 GB). Planning takes about 30 minutes with 4 workers. Requires Python 3 and
ffmpeg with VideoToolbox (macOS).

`dirdump.py` dumps exFAT directory entries of given clusters, including deleted
ones, for inspecting the file system by hand.

## Configuration

All scripts read the card geometry (cluster heap offset, cluster size, cluster
count) from `card.json` in the current directory, or from the file named in
`$CARD_CONFIG`. `card.py` writes it from the MBR and the exFAT boot sector.

`card.json` can also hold `header_overrides`: `{"<moov offset>": <header offset>}`
for clips whose header does not start on a cluster boundary. This happened once
on this card, where the camera's power-loss repair wrote the header 8 bytes into
its cluster. Such a header shows up in `scan2.txt` as an `ftyp` hit with a small
non-zero offset inside its cluster.

Clips with a `moov` but no header are found automatically and handled by
`lost3.py`. The header template for them is taken from the first intact file.

`names.py` takes the camera's time zone (IANA name), because DJI file names use
local time while the `moov` stores UTC.

The timestamp checks assume 59.94 fps (16683 us per frame).

## Result on this card

65 video indexes found. 64 videos written (about 3 h of 4K footage):

- 21 decode without any error.
- Most others have 1 to 6 short glitches of at most about 0.5 s each.
- One clip has its first 51 s overwritten; the oldest clip lost about 1 s to Spotlight.
- One older clip could not be recovered: only its last 0.3 s still existed.
