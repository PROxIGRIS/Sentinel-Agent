import time
t0 = time.time()
def p(name):
    print(f'{time.time()-t0:.2f}s: Importing {name}')

p('win32pdh')
import win32pdh
p('supabase')
import supabase
p('httpx')
import httpx
p('win32crypt')
import win32crypt
p('structlog')
import structlog
p('tkinter')
import tkinter as tk
p('pynput')
from pynput import keyboard
p('psutil')
import psutil
p('nacl')
import nacl.signing
p('websockets')
import websockets
print('Done!')
