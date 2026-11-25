#!/usr/bin/env bash
# make_testmedia.sh -- generate the small synthetic media library the scanner tests use.
#   bash tests/make_testmedia.sh [dir]     (default: tests/testmedia; needs ffmpeg)
# Everything is made from ffmpeg's built-in test patterns and tones -- no real films, nothing copyrighted.
set -euo pipefail
D="${1:-$(cd "$(dirname "$0")" && pwd)/testmedia}"
F="ffmpeg -hide_banner -loglevel error -y"
V720="-f lavfi -i testsrc2=size=1280x720:rate=24"
TONE="-f lavfi -i sine=frequency=440:sample_rate=48000"
mkdir -p "$D/movies/Big Test Movie (2019)" "$D/tv/Test Show/Season 01" "$D/tv/Test Show/Season 02" "$D/music/Test Artist/Test Album"
$F $V720 $TONE -t 60 -c:v libx264 -preset ultrafast -c:a aac "$D/movies/Big Test Movie (2019)/Big Test Movie (2019).mp4"
$F -f lavfi -i "color=c=0x6A16C4:size=640x960" -frames:v 1 "$D/movies/Big Test Movie (2019)/poster.jpg"
$F $V720 $TONE -t 75 -c:v libx264 -preset ultrafast -c:a ac3 "$D/movies/Remux Test (2022).mkv"
$F $V720 $TONE -t 50 -c:v libx264 -preset ultrafast -c:a mp2 -f mpegts "$D/movies/Transport Stream Clip (2018).ts"
$F -f lavfi -i testsrc=size=640x480:rate=25 $TONE -t 30 -c:v mpeg4 -c:a libmp3lame "$D/movies/Old Clip (1999).avi"
printf '1\n00:00:01,000 --> 00:00:04,000\nHello from the test subtitles.\n\n2\n00:00:05,000 --> 00:00:08,000\nSecond line.\n' > "$D/movies/Old Clip (1999).en.srt"
$F -f lavfi -i testsrc2=size=1920x1080:rate=24 $TONE -t 40 -c:v libx265 -preset ultrafast -x265-params log-level=error -c:a ac3 "$D/movies/Another.Film.2021.1080p.BluRay.x265.mkv"
for e in "Season 01/Test.Show.S01E01.Pilot.720p" "Season 01/Test.Show.S01E02.The.Second.One" "Season 02/Test.Show.S02E01.Return"; do
  $F $V720 $TONE -t 20 -c:v libx264 -preset ultrafast -c:a aac "$D/tv/Test Show/$e.mkv"
done
$F -f lavfi -i "color=c=0x2A1145:size=600x900" -frames:v 1 "$D/tv/Test Show/poster.jpg"
A="$D/music/Test Artist/Test Album"
$F -f lavfi -i "color=c=0xB07CFF:size=500x500" -frames:v 1 "$A/cover.tmp.jpg"
$F $TONE -i "$A/cover.tmp.jpg" -t 25 -map 0:a -map 1:v -c:a libmp3lame -c:v mjpeg -disposition:v attached_pic \
   -metadata title="First Song" -metadata artist="Test Artist" -metadata album="Test Album" -metadata track=1 "$A/01 - First Song.mp3"
rm -f "$A/cover.tmp.jpg"
$F -f lavfi -i sine=frequency=660:sample_rate=44100 -t 25 -metadata title="Second Song" -metadata artist="Test Artist" -metadata album="Test Album" -metadata track=2 "$A/02 - Second Song.flac"
$F -f lavfi -i sine=frequency=550:sample_rate=44100 -t 25 -c:a wmav2 -metadata title="Third Song" -metadata artist="Test Artist" -metadata album="Test Album" -metadata track=3 "$A/03 - Third Song.wma"
echo "$D"
