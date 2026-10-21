"""Give Codex a controlling PTY while its explicit '-' input is a regular file.

Some CLI releases stall before producing output in detached service contexts.
This single-threaded helper avoids forking the multi-threaded inbox server.
It never uses a shell or places conversation text in process arguments.
"""
import errno
import os
import pty
import select
import signal
import sys
import tempfile
import time


def main():
    prompt=sys.stdin.buffer.read()
    with tempfile.TemporaryFile() as source:
        source.write(prompt);source.flush();source.seek(0)
        pid,master=pty.fork()
        if pid==0:
            os.dup2(source.fileno(),0)
            os.execv(sys.argv[1],sys.argv[1:])
        deadline=time.monotonic()+135
        try:
            while time.monotonic()<deadline:
                ready,_,_=select.select([master],[],[],.25)
                if ready:
                    try:data=os.read(master,65536)
                    except OSError as e:
                        if e.errno==errno.EIO:break
                        raise
                    if not data:break
                    sys.stderr.buffer.write(data);sys.stderr.buffer.flush()
                done,status=os.waitpid(pid,os.WNOHANG)
                if done:return os.waitstatus_to_exitcode(status)
            else:
                os.killpg(pid,signal.SIGKILL)
                os.waitpid(pid,0)
                return 124
            _,status=os.waitpid(pid,0)
            return os.waitstatus_to_exitcode(status)
        finally:
            os.close(master)


if __name__=='__main__':sys.exit(main())
