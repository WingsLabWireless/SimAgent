import struct
import time
import socket 
from collections import deque
import threading 
import os
import sys 

from dataclasses import astuple, dataclass, field

### TODO: need to make sure we have access to 'pkt_base.py' and all imports therein wherever emulator is called 
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.getcwd() + '/ProtocolFolder/')
sys.path.insert(0, os.getcwd() + '/ProtocolFolder/dataPlane/')

# NOTE: this is specific to the protocol stack used to develop SimAgent privately, which cannot be shared open-source at this time 
from ProtocolFolder.dataPlane import pkt_base


@dataclass
class node_info:
    """ Convenience class for node info management """
    node_id : int = None
    freq_tx : int = 2400 # used to map transmitted packets to receive hosts - initial values should be overwritten on node discovery 
    freq_rx : int = 2450 # ^ 
    gain_tx : int = -10 # used to support existing signaling between ZTOS and MPSoC - initial values are arbitrary 
    gain_rx : int = 50 # ^ 
    docker_ip_addr : int = None
    listener_port : int = None

    def __iter__(self):
        return iter(astuple(self))



class channel_buffer:
    """
    Simple class implementing a packet queue with frequency assignment 

    TODO: profile timing - must be strictly faster than transmit processes 
    """
    def __init__(self, frequency):
        self.freq = frequency
        self.buffer = deque(maxlen=1000) 
        self.addr_list = [] # record node ipaddrs currently receiving frequency for forwarding 
    
    def add_packet(self, packet):
        """
        Store a packet and receive time in the channel buffer as a tuple 
        """
        self.buffer.appendleft((time.time(), packet))

    def get_packet(self):
        """
        Get a packet from the channel buffer queue if available, otherwise return null tuple 
        """
        if self.buffer:
            return self.buffer.pop()
        else:  
            return None 



class emu_channel: # what does a flightless bird watch on TV?
    """
    Packet forwarding interface for containerized node communication 

    Each node will be assigned its own UDP listener socket to enable collisions 

    NOTE: if path 2 is needed, it might be easier just to run a second instance of this program, adjusting IP/port allocation to suit 
    """
    def __init__(self, network_gw_addr, dynamic):
        # bind listener sockets to Docker bridge network gateway address 
        self.listener_ip = network_gw_addr

        # set flag to determine dynamic creation of node contexts 
        self.dynamic = dynamic

        # frame receive process duration at FPGA, in sec 
        self.frame_duration = 0.0026


        # declare port to receive control signals from nodes 
        self.ctrl_port = 40001
        self.node_rx_path_port = 52017 # NOTE: this is the same for every node (path 1 only) (# "phy_emu_path1_prt_num" # TODO: sync with global port config)
        self.node_ctrl_iface_port = 52013 # NOTE: ^ ^ ^ (# "port_emu_monitor_path1" # TODO: sync with global port config)

        # initialize node info dict - this will be used to assoc IP addr with node info and create/access channel buffer objects 
        self.ipaddr_context = {}

        # list of buffers by frequency 
        self.buffer_dict = {}
        # --> NOTE: one buffer will be initialized for each frequency set by nodes in the network 

        # list of handles for listener sockets 
        self.socket_handles = []

        # list of process thread handles (including listener threads and buffer processing threads) 
        self.thread_handles = []

        # create control socket, bind to Docker network gateway address and control port, and start listener thread 
        self.ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl_sock.bind((network_gw_addr, self.ctrl_port))


    def add_listener(self, port: int):
        """
        Spawn listener socket, bind to specified addr/port, and start listener thread 
        """
        lsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        lsock.bind((self.listener_ip, port))
        self.socket_handles.append(lsock) # <-- not sure if we need to retain handle 

        lthread = threading.Thread(target = self.listener_iface, args = [lsock], daemon=True)
        self.thread_handles.append(lthread) # <-- not sure if we need to retain handle 
        lthread.start()


    def listener_iface(self, socket_handle: socket.socket):
        """
        Receive data from node on specified socket and add to buffer associated with TX node frequency 
        """
        n_pkts = 0
        while True: 
            data, (addr, port) = socket_handle.recvfrom(9000) # use 'recvfrom' to cross-reference node docker host info 

            if data: 
                # get frequency of transmitting node 
                on_freq = self.ipaddr_context[addr].freq_tx

                # print(f"adding pkt to buffer at {addr}")

                # add packet to buffer on specified frequency 
                self.buffer_dict[on_freq].add_packet(data)

                n_pkts += 1
                # print(f"Buffered {n_pkts} frames")

            # print(f'got data from {addr}')
            # socket_handle.sendto(b'\x00\x00\x00\x00', (addr, self.node_rx_path_port))



    def add_buffer(self, freq: int):
        """
        Add buffer for this frequency and start buffer processing loop 
        """
        # double-check that buffer does not exist - duplicate buffers would be detrimental 
        if freq in self.buffer_dict:
            return 
         
        self.buffer_dict[freq] = channel_buffer(frequency = freq) 

        bthread = threading.Thread(target = self.process_buffer, args = [freq], daemon=True)
        self.thread_handles.append(bthread) 
        bthread.start()


    def process_buffer(self, freq: int):
        """
        Fetch packets from buffer at specified frequency and evaluate forwarding 
        """
        print(f"Starting buffer thread on freq: {freq}")

        n_drops = 0
        n_sent = 0

        last_frame_time = time.time() 
        while True: 
            # check for packet 
            if self.buffer_dict[freq].buffer: 
                frame_time, data = self.buffer_dict[freq].get_packet()
                n_sent += 1

                # check for collision at receiver 
                if frame_time - last_frame_time < self.frame_duration:
                    # frame was received before previous frame has been processed - drop
                    n_drops += 1
                    print(f"drop (ratio: {n_drops / n_sent} -- {n_drops} / {n_sent}) - gap: {frame_time - last_frame_time}")
                    continue 
                
                # if no collision, forward frame to all nodes receiving on this frequency 
                else: 
                    # print(f"sending on freq {freq}")
                    for addr in self.buffer_dict[freq].addr_list: 
                        # print(f"\tto {addr}")
                        self.ctrl_sock.sendto(data, (addr, self.node_rx_path_port))

                    # record start time of frame 'transmission' 
                    last_frame_time = time.time()

            # if no packet available, sleep (TODO: might be better to use blocking call, since buffer threads will be separate)
            else: 
                time.sleep(0.0001) 



    def add_node(self, ipaddr):
        """
        Create context for virtual node 
        """
        # if node is not known, use known IP addr and listener port mapping to get ID 
        node_id = int(ipaddr.split('.')[-1]) - 1 
        listener_port = self.ctrl_port + node_id 
        
        # record node info  
        self.ipaddr_context[ipaddr] = node_info(node_id = node_id, docker_ip_addr = ipaddr, listener_port = listener_port)
        
        # bind listener socket and start thread 
        self.add_listener(listener_port)



    def control_iface(self):
        """
        Listener thread for EMU control socket 

        Node contexts are created dynamically (if not known) to simplify startup, since all nodes exchange control signals with MPSoC on startup 
        
        Received signals are expected to follow INFORMAL "pkt_base.Packet_Ctrl.payload_bytes" formatting without header/msgType 
        # NOTE: this limits flexibility, but mirrors actual signaling logic between IIO module and MPSoC 
        """
        # define dummy pkt for sending ZTOS signals to Lyr1 (which then forwards to ZTOS)
        ctrl_pkt = pkt_base.Packet_Ctrl(msg_type=pkt_base.msgType_ztos_sig, payload_bytes=b'\x00')

        while True: 
            ctrl_sig, (addr, port) = self.ctrl_sock.recvfrom(4000) # use 'recvfrom' to cross-reference node docker host info 

            # if node is not known, check if context should be created dynamically 
            if addr not in self.ipaddr_context: 
                if self.dynamic:
                    print(f"Creating context for node at {addr}")
                    self.add_node(ipaddr = addr)
                else: 
                    # if not accepting dynamic connections, just ignore unknown IP's 
                    print(f"No node context for signal from {addr}:{port} (ignoring): <{repr(ctrl_sig)}>")
                    continue 
            
            try: 
                # NOTE: control payload formatting is not strictly defined, but command context string should be first 4 bytes  
                command = ctrl_sig[0:4].decode('latin1')
            except: 
                print(f"Could not decipher control signal <{repr(command)}> - ignoring")
                continue 

            # Check the command type
            if command == 'GAIN':
                path_id, set_flag = struct.unpack('<B?', ctrl_sig[4:6])

                if path_id != 1: # path 2 not supported yet 
                    continue 

                if set_flag: 
                    print(f"Got 'SET gain' from {addr} (node {self.ipaddr_context[addr].node_id})") 
                    self.ipaddr_context[addr].gain_tx, self.ipaddr_context[addr].gain_rx = struct.unpack('<bb', ctrl_sig[6:8])
                else: 
                    print(f"Got 'GET gain' from {addr} (node {self.ipaddr_context[addr].node_id})") 

                # Send the current gain values to Lyr1 to forward to ZTOS
                ctrl_pkt.payload_bytes = pkt_base.payload_ZTOS(
                    proc_id = pkt_base.pID_txrx_gain, node_id = 0, path_id = 1,
                    payload_bytes = struct.pack('<bb', self.ipaddr_context[addr].gain_tx, self.ipaddr_context[addr].gain_rx) 
                ).pack()
                self.ctrl_sock.sendto(ctrl_pkt.pack(), (addr, self.node_ctrl_iface_port)) 

            elif command == 'FREQ':
                path_id, set_flag = struct.unpack('<B?', ctrl_sig[4:6])

                if path_id != 1: # path 2 not supported yet 
                    continue 

                if set_flag: 
                    freq_tx, freq_rx = struct.unpack('<HH', ctrl_sig[6:10])
                    print(f"Got 'SET freq' from {addr} (node {self.ipaddr_context[addr].node_id}): {freq_tx},{freq_rx}") 

                    # whenever a frequency is set, check if we need to create new buffers, then update buffer lists 
                    if freq_tx not in self.buffer_dict:
                        self.add_buffer(freq = freq_tx)
                    if freq_rx not in self.buffer_dict:
                        self.add_buffer(freq = freq_rx)
                    
                    # update buffer lists - first remove addr if it exists in current buffer lists, then add it to addr list of buffer at new RX frequency 
                    for key, val in self.buffer_dict.items():
                        if addr in val.addr_list:
                            val.addr_list.remove(addr)
                    self.buffer_dict[freq_rx].addr_list.append(addr)

                    # assign new values to node context object 
                    self.ipaddr_context[addr].freq_tx = freq_tx
                    self.ipaddr_context[addr].freq_rx = freq_rx
                else: 
                    print(f"Got 'GET freq' from {addr} (node {self.ipaddr_context[addr].node_id})") 

                # Send the current frequency values to ZTOS
                print(f"Sending response to {addr}:{self.node_ctrl_iface_port}")
                
                ctrl_pkt.payload_bytes = pkt_base.payload_ZTOS(
                    proc_id = pkt_base.pID_txrx_freq, node_id = 0, path_id = 1,
                    payload_bytes = struct.pack('<HH', self.ipaddr_context[addr].freq_tx, self.ipaddr_context[addr].freq_rx)
                ).pack()
                self.ctrl_sock.sendto(ctrl_pkt.pack(), (addr, self.node_ctrl_iface_port)) 
                
            elif command == 'AGCC':
                # this can be ignored, since EMU channel has no RF front-end 
                print(f"Ignoring AGC config command from {addr} (node {self.ipaddr_context[addr].node_id})")               
                
            else:
                print(f'Unknown/unsupported command type: <{command}>')




if __name__ == "__main__":
    # get list of "ipaddr:port" for each node - NOTE: might not be needed 
    node_args = sys.argv[1:]

    # parse network gateway address from docker IPs 
    ex_ipaddr = node_args[0].split(':')[0]
    gw_addr = f"{ex_ipaddr.split('.')[0]}.{ex_ipaddr.split('.')[1]}.{ex_ipaddr.split('.')[2]}.1"

    print(f"Binding channel emulator to network gateway address: {gw_addr}")

    # create channel emulator object 
    emulator = emu_channel(network_gw_addr = gw_addr, dynamic = False)
    # --> NOTE: the following block is not needed if 'dynamic==True', but it might be more reliable to trust script-generated IP's 
    

    # parse inputs, spawn listener sockets, and store node info 
    for ip_info in node_args:
        ipaddr, port = ip_info.split(":")
        emulator.add_listener(int(port))
        
        # NOTE: for now, node ID == host ID of IP addr - 1
        temp_node_id = int(ipaddr.split('.')[-1]) - 1
        emulator.ipaddr_context[ipaddr] = node_info(node_id = temp_node_id, docker_ip_addr = ipaddr, listener_port = int(port))

    # NOTE: unless specified globally, resource buffers will need to be created dynamically based on node frequency commands 

    # give main thread to control socket listener for now (TODO: replace with packet processing operations? at least add them as threads)
    emulator.control_iface()

