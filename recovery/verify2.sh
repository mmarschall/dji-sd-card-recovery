#!/bin/zsh
# full hardware decode; prints name, decoder error count and the frame numbers they occur at
out=$1; shift
for f in "$@"; do
  n=${f:t}
  ffmpeg -nostdin -hide_banner -hwaccel videotoolbox -i "$f" -map 0:v:0 -vf showinfo -f null - 2>&1 \
   | awk '/n: *[0-9]+ /{match($0,/n: *[0-9]+/); split(substr($0,RSTART,RLENGTH),a,":"); last=a[2]+0; nf++; next}
          /rror|failed|No frame/{err++; if(!(last in seen)){seen[last]=1; fr=fr" "last}}
          END{printf "%s errors=%d decoded=%d at:%s\n", N, err+0, nf+0, fr}' N="$n"
done
