import argparse
import socket
import ssl
import threading

import security_core

BUFFER_SIZE = 4096
SOCKET_TIMEOUT = 10


def relay(source, destination):
    try:
        while True:
            data = source.recv(BUFFER_SIZE)
            if not data:
                break
            destination.sendall(data)
    except socket.timeout:
        pass
    except Exception:
        pass
    finally:
        for sock in (source, destination):
            try:
                sock.close()
            except Exception:
                pass


def handle_connection(client_conn, addr, target_host, target_port, target_tls=False, target_tls_context=None, send_proxy_header=False):
    addr_str = str(addr)
    try:
        if security_core.is_blocked(addr_str) or security_core.register_connection_activity(addr_str):
            client_conn.close()
            return
    except Exception as e:
        print(f"[PROXY] Security check error (fail-open): {e}")

    client_conn.settimeout(SOCKET_TIMEOUT)
    try:
        target_conn = socket.create_connection((target_host, target_port), timeout=SOCKET_TIMEOUT)
        if target_tls:
            if target_tls_context is None:
                target_tls_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                target_tls_context.check_hostname = False
            target_conn = target_tls_context.wrap_socket(target_conn, server_hostname=target_host)
        target_conn.settimeout(SOCKET_TIMEOUT)

        if send_proxy_header:
            try:
                proxy_line = f"PROXY {addr[0]} {addr[1]}\n"
                target_conn.sendall(proxy_line.encode('utf-8'))
            except Exception as e:
                print(f"[PROXY] Could not send PROXY header: {e}")
                target_conn.close()
                client_conn.close()
                return
    except Exception as e:
        print(f"[PROXY] Could not reach target {target_host}:{target_port}: {e}")
        client_conn.close()
        return

    threading.Thread(target=relay, args=(client_conn, target_conn), daemon=True).start()
    threading.Thread(target=relay, args=(target_conn, client_conn), daemon=True).start()


def build_ssl_context(cert_file, key_file):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def main():
    parser = argparse.ArgumentParser(description="Proxy TCP de sécurité, attachable à n'importe quel service TCP")
    parser.add_argument('--listen-host', default='0.0.0.0')
    parser.add_argument('--listen-port', type=int, required=True)
    parser.add_argument('--target-host', default='127.0.0.1')
    parser.add_argument('--target-port', type=int, required=True)
    parser.add_argument('--tls-cert', default=None)
    parser.add_argument('--tls-key', default=None)
    parser.add_argument('--target-tls', action='store_true', help='Use TLS when connecting to the target server')
    parser.add_argument('--target-ca', default=None, help='CA certificate file to verify the target TLS server certificate')
    parser.add_argument('--proxy-header', action='store_true', help='Send a PROXY header with the original client address to the target')
    args = parser.parse_args()

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_socket.bind((args.listen_host, args.listen_port))
    listen_socket.listen(10)

    ssl_context = build_ssl_context(args.tls_cert, args.tls_key) if args.tls_cert and args.tls_key else None
    target_tls_context = None
    if args.target_tls:
        target_tls_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        target_tls_context.check_hostname = False
        if args.target_ca:
            target_tls_context.load_verify_locations(args.target_ca)
        elif args.tls_cert:
            target_tls_context.load_verify_locations(args.tls_cert)

    print(
        f"[PROXY] {args.listen_host}:{args.listen_port} -> {args.target_host}:{args.target_port} "
        f"| TLS incoming: {'on' if ssl_context else 'off'} "
        f"| TLS outgoing: {'on' if args.target_tls else 'off'} "
        f"| PROXY header: {'on' if args.proxy_header else 'off'}"
    )

    try:
        while True:
            conn, addr = listen_socket.accept()
            if ssl_context:
                try:
                    conn = ssl_context.wrap_socket(conn, server_side=True)
                except ssl.SSLError as e:
                    print(f"[TLS] Handshake failed with {addr}: {e}")
                    conn.close()
                    continue
            threading.Thread(
                target=handle_connection,
                args=(conn, addr, args.target_host, args.target_port, args.target_tls, target_tls_context, args.proxy_header),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down...")
    finally:
        listen_socket.close()


if __name__ == '__main__':
    main()