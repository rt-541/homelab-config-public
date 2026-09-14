# go2rtc

Restreams the Prusa printer's RTSP feed to browser-playable formats (MSE/HLS)
for embedding on about.rt-541.io/maker.

- Source: `rtsp://192.168.1.220/live` (LAN, no auth)
- Published at `cam.rt-541.io` (Traefik, TLS via default resolver)
- Stream name: `printer`
- Player: `https://cam.rt-541.io/stream.html?src=printer&mode=mse`

## Add a stream

Edit `go2rtc.yaml` under `streams:` then `sudo docker compose down && sudo docker compose up -d`.

## Note

The endpoint is public. The /maker page uses click-to-load so it does not
auto-broadcast, but anyone with the URL can watch. Add basic-auth on the
Traefik router if you need to lock it down.
