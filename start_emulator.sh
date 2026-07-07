#!/bin/bash


# default network size: 3 (NOTE: first node is always started as GBS/PCN)
n_nodes=${1:-3}


# give local connections (i.e. docker containers) access to display back-end 
xhost +local:

# define IP addresses and ports for each node connection 


# Static IP address allocation on custom bridge network 172.22.0.0/24:
# - 172.22.0.1: network gateway - addr of channel listener sockets 
# - 172.22.0.N: addr of node N on network 

# Port assignment: 
# - channel control port = 40000
# - channel listener ports: 40001 + N, where N is node ID [0,:)
# - node hosts do not need unique ports, since they will be sorted by IP 



# --> start address for node IPs; host ID for channel EMU IP bound to network gateway 
network_gw_host_id=1 

# --> start address for channel listener ports; port for EMU control signaling 
channel_control_port=40001 

# start docker bridge network 'emunet' (close if opened before)
if echo "$(docker network ls)" | grep -q "emunet"; then 
    docker network rm emunet
fi 
docker network create --subnet=172.22.0.0/24 emunet


# intialize IP array 
iparr=()

# TODO: give USB camera permissions to GBS, since it is easy to differentiate (and easy to remember) 

# for i in {1..$n_nodes}; do --> syntax {a..b} only works with literals
for ((i=1;i<=$n_nodes;++i)); do 
    # define IP address this node 
    node_host_id="172.22.0.$((network_gw_host_id+$i))"

    # define channel host listener port 
    chan_port=$((channel_control_port+$i))

    printf "Adding node at host: %s, listener port: %s\n" "$node_host_id" "$chan_port" 

    # # start docker for this node - use new terminal, since we will need to tmux 
    # gnome-terminal -- sh -c "bash -c \"docker run --network emunet --ip $node_host_id -it --rm -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY [docker_name]; exec bash\""

    # start docker for this node - use new terminal, since we will need to tmux (let terminal die when container closes) 
    # --> start GBS with USB camera permissions - MUST GET CORRECT USB DEVICE, recommend using "$ ls /dev " to check for "/dev/video0" or "/dev/video1"
    # if [ $i -eq 1 ]; then
    if [ $i -eq 2 ]; then
        gnome-terminal -- sh -c "bash -c \"docker run --network emunet --ip $node_host_id -it --device=/dev/video0 --rm -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY [docker_name]\""
    else
        gnome-terminal -- sh -c "bash -c \"docker run --network emunet --ip $node_host_id -it --rm -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY [docker_name]\""
    fi
    # build array of IP addr/port allocations 
    iparr+=("$node_host_id:$chan_port")

    printf "Host %s added!\n" "$node_host_id"  
done 

echo "${iparr[@]}"


# start channel emulation program, passing IP/port array as sys.argv  
exec python3 emulator_channel.py ${iparr[@]} 
# --> this should probably start before ztswarm instances when automated 


# # close docker network - NOTE: this relies on the assumption that Python channel EMU script blocks correctly  
exec docker network rm emunet




# -----> docker-compose might be the formally 'correct' way of doing this, but support for individual GUIs is not apparent 


