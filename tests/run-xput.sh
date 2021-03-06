#!/bin/bash

dir=`date +%b%d-%H:%M`
time=40
ns=0

function finish {
    killall -9 ssh
    exit
}

trap finish SIGINT

mkdir -p $dir
for rl in qfq; do
for nrls in 1; do
for rate in 1000 3000 5000 7000 9000; do
    exptid=rl-$rl-nrls-$nrls-rate-$rate
    python netperf.py --nrr 0 \
        --exptid $exptid \
        -t $time \
        --rl $rl \
        --rate $rate \
        --nrls $nrls \
	--ns 4 # 4 flows should give line rate


    mv $exptid.tar.gz $dir/

    pushd $dir;
    tar xf $exptid.tar.gz
    #python ../plot.py --rr $exptid/* -o $exptid.png --ymin 0.9
    popd;
done;
done;
done;

echo Experiment results are in $dir
