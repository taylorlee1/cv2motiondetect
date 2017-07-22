#! /bin/bash
free -m | tail -2| head -1 | awk '{print $NF}'
