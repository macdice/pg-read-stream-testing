

PID="`ps aux | grep 'postgres: .* postgres' | grep -v grep | sed 's/^[^ ]* *//;s/ .*//'`"
strace -p $PID -T -s100 2>&1 | tee $1
