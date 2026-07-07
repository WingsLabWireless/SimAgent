#!/bin/bash

# default node ID should be host ID of IP addr (i.e. last field) minus 1 - this will sync with EMU channel node interface ID's 
IFS="." read -ra ipaddr_as_arr <<< $(hostname -I)
default_id=$((${ipaddr_as_arr[-1]} - 1))

# # --> alternate method 
# own_ipaddr=$(hostname -I)
# ipaddr_as_arr=(${own_ipaddr//./ })
# default_id=$((${ipaddr_as_arr[-1]} - 1))

node_id=${1:-${default_id}}
# if node ID == 1 (i.e. IP addr == X.X.X.2), this is the first container started (.1 is only for network GW) - set as GBS/PCN, otherwise HDR 
# --> this affects defaults only, i.e. when no cmd line args are provided 
if [[ "$node_id" -eq 1 ]]; then 
    node_type=${2:-'gbs'}
else
    node_type=${2:-'hdr'}
fi 
n_paths=${3:-1}
n_ffc=${4:-6}


# set terminal window title to indicate this node 
echo -ne "\033]0;P::node_$node_id\007"



# Get packet size and frame buffer size from 'n_ffc'
PHYARG1=$((256 - 16*n_ffc))
PHYARG2=$((2048 - 128*n_ffc))
# echo "$PHYARG1 $PHYARG2"

# start tmux session for desktop GUI (detached, otherwise)
tmux new-session -d -s zt 
tmux rename-window -t zt:0 'p_main'

# # activate conda environment in tmux session and clear output 
# --> NOTE: not necessary if using configuration from local '~/.tmux.conf'
# tmux send-keys -t zt "conda activate ztswarm" ENTER 'clear' ENTER
# NEW
tmux send-keys -t zt "conda activate ntwk_env" ENTER 'clear' ENTER

# # print input args to double-check values 
tmux send-keys -t zt "echo $'\nnode id = $node_id \nnode type = $node_type \nn paths = $n_paths \nn_ffc = $n_ffc'" ENTER

# open 9 windows in tile layout and start ZTSwarm layers 
# --> NOTE: pane numbers are not persistent - panes are re-numbered L->R/T->B whenever a pane is added/split 

# Make 3 rows by splitting vertical area proportionally 
tmux splitw -v -l 66% -t zt:0.0
tmux splitw -v -l 50% -t zt:0.1
# row 1: zt:0.0
# row 2: zt:0.1
# row 3: zt:0.2

# split first row into 3 columns 
tmux splitw -h -l 66% -t zt:0.0
# --> now, first row: [ zt:0.0 ][      zt:0.1      ]
tmux splitw -h -l 50% -t zt:0.1
# --> now, first row: [ zt:0.0 ][ zt:0.1 ][ zt:0.2 ]

# split second row into 3 columns 
tmux splitw -h -l 66% -t zt:0.3
# --> now, second row: [ zt:0.3 ][      zt:0.4      ]
tmux splitw -h -l 50% -t zt:0.4
# --> now, second row: [ zt:0.3 ][ zt:0.4 ][ zt:0.5 ]

# split third row into 3 columns 
tmux splitw -h -l 66% -t zt:0.6
# --> now, first row: [ zt:0.6 ][      zt:0.7      ]
tmux splitw -h -l 50% -t zt:0.7
# --> now, first row: [ zt:0.6 ][ zt:0.7 ][ zt:0.8 ]

# # check pane assignment
# tmux clock -t zt:0.0
# tmux clock -t zt:0.4
# tmux clock -t zt:0.8

# start independent protocol processes -- NOTE: these scripts are TEMPLATES ONLY and will not run without an accompanying protocol stack 
tmux send-keys -t zt:0.0 "python3 dataPlane/hn_lyr1_emu.py -i $node_id -t $node_type -p $n_paths" ENTER
tmux send-keys -t zt:0.1 "python3 dataPlane/hn_lyr2.py -i $node_id -t $node_type -p $n_paths" ENTER
tmux send-keys -t zt:0.2 "python3 dataPlane/hn_lyr3.py -i $node_id -t $node_type -p $n_paths" ENTER
tmux send-keys -t zt:0.3 "python3 dataPlane/hn_lyr4.py -i $node_id" ENTER
tmux send-keys -t zt:0.4 "python3 dataPlane/hn_lyr5_main.py -v r -i $node_id" ENTER
tmux send-keys -t zt:0.5 "python3 dataPlane/hn_lyr5_main.py -v t -i $node_id" ENTER

# attach to session 
tmux a -t zt
