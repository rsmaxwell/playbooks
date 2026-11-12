#!/bin/bash

# starting
# running
# healthy

function healthcheck {
    echo $(docker inspect archiva-archiva | jq -r .[0].State.Health.Status)
}

SECONDS=0
health=$(healthcheck)
echo "health: $health"
while [ $health == "starting" ]; do

  if (( SECONDS > 120 )); then
     echo "Giving up..."
     exit 1
  fi

  sleep 5
  health=$(healthcheck)
  echo "health: $health"
done

if [ $health == "healthy" ]; then
  exit 0
fi

exit 2

