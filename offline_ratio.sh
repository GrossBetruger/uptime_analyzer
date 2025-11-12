curl -s http://34.55.225.231:3000/logs | grep -v -E "(OrenK)|(Drier)" | \
awk '{total++} /offline/{off++} END{
    if(off) printf "Total: %d | Offline: %d | Ratio: %.3f\n", total, off, off/total;
    else print "No offline lines found";
}'

