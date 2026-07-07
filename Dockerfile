# Create conda env from config file and update bashrc
FROM continuumio/miniconda3 AS condabuilder
COPY conda_environment.yaml /

RUN conda env create -f conda_environment.yaml && conda clean -a


# Load base image and install xterm
FROM ubuntu:22.04
RUN apt-get update 
RUN apt-get install -y nano 
RUN apt-get install -y tmux

# Copy relevant conda files to base image and initialize installation
COPY --from=condabuilder /opt/conda/ /opt/conda/
RUN ./opt/conda/condabin/conda init bash

# Configure environment variables to support Qt GUI display over xterm
RUN chmod 0700 /tmp/
ENV XDG_RUNTIME_DIR=/tmp
ENV QT_XCB_GL_INTEGRATION=none

# Add conda executables to path in base image
ENV PATH=/opt/conda/bin:$PATH
ENV PATH=/opt/conda/envs/ntwk_env/bin:$PATH


# Activate environment on startup
RUN echo "source activate ntwk_env" > ~/.bashrc


# Initialize tmux config file (NOTE: need to use '-e' to support escaped double-quotes)
RUN echo "bind -n C-q kill-session \n\
setw -g mouse on \n\
set-hook -g client-resized 'selectl tiled' \n\
set-hook -g after-new-window 'send-keys \"conda activate ntwk_env\" ENTER' \n\
set-hook -g after-split-window 'send-keys \"conda activate ntwk_env\" ENTER' "  > ~/.tmux.conf 


# # Copy application code -- NOTE: this must be an available software-defined protocol stack folder 
COPY ProtocolFolder /home/

# Make emulation startup script executable
RUN chmod +x /home/protocol_script.sh

# Change CWD to the top-level protocol folder (or else relative imports may fail)
WORKDIR /home/

# Start ZTSwarm when container starts, using default config (node ID set by IP host ID; lowest IP == GBS/PCN, all others started as headers; 1 RF path)
CMD ["/bin/sh", "-c", "./protocol_script.sh"]


# NOTE: 

# NOTE-BUILD: $ docker build -t [docker_name] . 
# NOTE-RUN:   $ docker run -it --rm -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY [docker_name] 
# --> if QT plugins cannot open display, run: '$ xhost +local:'

# NOTE-START user-defined bridge network 'emunet': $ docker network create --subnet=172.22.0.0/24 emunet
# NOTE-RUN on user-defined bridge network 'emunet' with static IP: $ docker run --network emunet --ip 172.22.0.2 -it --rm -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY [docker_name]

# NOTE: can only send packets out of container when "--network=host" flag used on run 

# NOTE: stop all running containers: $ docker stop $(docker ps -a -q)

# NOTE: check ".dockerignore" for all files excluded from build 
