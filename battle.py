import tkinter as tk
import socket
import threading
from tkinter import messagebox
import queue
import select
import time

class ScrollFrame(tk.Frame):
    def __init__(self, root, **kwargs):
        tk.Frame.__init__(self, root, **kwargs)

        self.messages = list()

        self.canvas = tk.Canvas(root, bd=0, bg="#ffffff")
        self.frame = tk.Frame(self.canvas, bg="#ffffff")
        self.scrollbar = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.create_window((4, 4), window=self.frame, anchor="nw", tags="self.frame")

        self.frame.bind("<Configure>", self.on_configure)

    def on_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def add_text(self, text):
        if len(text) > 44:
            print("Message size exceeded buffer.")
            return
        message_no = len(self.messages)
        tk.Label(self.frame, text=text).grid(row=message_no, column=0, sticky="W")
        self.messages.append(text)

class ChatWindow:
    def __init__(self, app):
        self.app = app
        # --GUI-- #
        self.root = tk.Tk()
        self.root.title("Chat Room!")

        self.entry = tk.Entry(self.root, width=50)
        self.submit = tk.Button(self.root, text="Send", command=self.send)
        self.root.bind('<Return>', self.send)

        self.entry.pack()
        self.submit.pack()

        self.chat_window = ScrollFrame(self.root)
        self.chat_window.pack(side="top", fill="both", expand=True)

        self.root.mainloop()
        
    def send(self):
        msg  = self.entry.get()
        if msg:
            self.app.game.out_queue.put("*"+msg)
            self.chat_window.add_text("You: "+msg)
        
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Battleships")
        self.root.configure(bg="turquoise3")
        # Server
        self.s = socket.socket()
        self.server = (socket.gethostname(), 54321)
        # Client or Server var
        self.c_s = ""
        # Declarations
        self.menu = MainMenu(self)
        self.wait = Waiting(self)
        self.con = Connect(self)
        self.game = Game(self)

        # Use of
        self.display = self.menu
        self.display.draw()
        
        self.root.mainloop()

    def create_server(self):
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind(self.server)
        
        self.s.listen(5)

        self.set_display(self.wait)

        self.c_s = "s"
        
        t = threading.Thread(target=self.wait.listen)
        t.setDaemon(True)
        t.start()

    def set_display(self, to):
        self.display.undraw()
        self.display = to
        self.display.draw()
        self.root.geometry("")

    def connect(self, to):
        try:
            if to:
                self.s.connect((to, 54321))
            else:
                self.s.connect(self.server)
            self.c_s = "c"
            return True

        except ConnectionRefusedError:
            self.popup("warning", "Could not connect to supplied server.\nIs the server running?")
            return False

        except OSError:
            self.popup("warning", "Could not connect to supplied server.\nIs the server running?")
            return False

    @staticmethod
    def popup(box, msg):
        if box == "info":
            messagebox.showinfo("Information", msg)
        if box == "warning":
            messagebox.showwarning("Warning", msg)
        if box == "error":
            messagebox.showerror("Error", msg)


class MainMenu:
    def __init__(self, app):
        self.app = app
        self.host_button = tk.Button(text="Host Game", width=10, font=("Verdana", 17, "bold"), bg="turquoise3",
                                     fg="light cyan", command=self.app.create_server)
        self.join_button = tk.Button(text="Join Game", width=10, font=("Verdana", 17, "bold"), bg="turquoise3",
                                     fg="light cyan", command=lambda: self.app.set_display(self.app.con))

    def draw(self):
        self.host_button.grid(column=0, row=0)
        self.join_button.grid(column=0, row=1)

    def undraw(self):
        self.host_button.grid_forget()
        self.join_button.grid_forget()


class Waiting:
    def __init__(self, app):
        self.app = app
        
        self.host_info = tk.Label(text="Hosting on {}:{}".format(*self.app.server), font=("Verdana", 17, "bold"),
                                  bg="turquoise3", fg="light cyan")

    def listen(self):
        print("listening on", *self.app.server)
        client, address = self.app.s.accept()
        print("... connected from", address)
        t = threading.Thread(target=self.app.game.handler, args=(client, address))
        t.setDaemon(True)
        t.start()
        self.app.set_display(self.app.game)

    def draw(self):
        self.host_info.grid(row=0, column=0)

    def undraw(self):
        self.host_info.grid_forget()


class Connect:
    def __init__(self, app):
        self.app = app

        self.ip_lab = tk.Label(text="Server IP: ", font=("Verdana", 17, "bold"), bg="turquoise3", fg="light cyan")
        self.ip_entry = tk.Entry(font=("Verdana", 17, "bold"), bg="white", fg="black")
        self.connect_button = tk.Button(text="Connect", bg="turquoise3", font=("Verdana", 13, "bold"),
                                        fg="light cyan", command=self.attempt)

    def attempt(self):
        txt = self.ip_entry.get()
        if self.app.connect(txt):
            self.app.set_display(self.app.game)
            t = threading.Thread(target=self.app.game.handler, args=(self.app.s, "Server"))
            t.setDaemon(True)
            t.start()

    def draw(self):
        self.ip_lab.grid(row=0, column=0)
        self.ip_entry.grid(row=1, column=0)
        self.connect_button.grid(row=2, column=0)

    def undraw(self):
        self.ip_lab.grid_forget()
        self.ip_entry.grid_forget()
        self.connect_button.grid_forget()


class Game:
    def __init__(self, app):
        self.app = app
        # NETWORK
        self.in_queue = queue.Queue()
        self.out_queue = queue.Queue()
        self.chat_queue = queue.Queue()
        self.disc_flag = threading.Event()
        # MISC
        self.loop = False
        self.window = threading.Thread(target=self.start_chat)
        self.th = threading.Thread(target=self.fixed_update)
        self.th.setDaemon(True)
        self.th.start()
        # GAME
        self.state = "select"
        self.selected = []
        self.ship_no = 21
        self.ship_rem = 21
        # GUI
        self.chatwindow = ''
        self.info = tk.Label(text="Select your ship positions. (21)", font=("Verdana", 15, "bold"),
                             bg="turquoise3", fg="light cyan")
        self.action_but = tk.Button(text="Confirm?", state="disabled", command=self.action)

        self.show_but = tk.Button(text="Show ships", state="disabled",
                                  command=lambda: self.toggle('s', True))
        self.board_but = tk.Button(text="Show your board", state="disabled", command=lambda: self.toggle('b', 'm'))

        # Board setup
        self.en_board_ref = [['' for v in range(11)] for c in range(11)]
        self.board_reference = [['' for v in range(11)] for c in range(11)]
        self.board_gui = [['' for v in range(11)] for c in range(11)]

        alp = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for x in range(11):
            for y in range(11):
                if x == 0 or y == 0:
                    text = ""
                    if x == 0:
                        text = y
                    elif y == 0:
                        text = alp[x-1]

                    if (x+y) % 2 == 0:
                        col = "cadetblue2"
                    else:
                        col = "cadetblue3"
                    self.board_gui[y][x] = tk.Label(text=text, bg=col, font=("Verdana", 16, "bold"),
                                                    width=2)
                else:
                    if (x+y) % 2 == 0:
                        col = "grey87"
                    else:
                        col = "grey72"
                    self.board_gui[y][x] = tk.Button(text="", bg=col, font=("Verdana", 12, "bold"),
                                                     width=2, height=1, command=lambda i=x, o=y: self.click(i, o))

    def fixed_update(self):
        while 1:
            if self.loop:
                if not self.in_queue.empty():
                    msg = self.in_queue.get()
                    if msg == "done":
                        if self.state == "picked":
                            self.state = "playing_c"
                        if self.state == "select":
                            while self.state == "select":
                                time.sleep(1)
                            self.state = "playing_c"
                    if msg[0] == "?":
                        if self.state == "playing_w":
                            sp = msg[1:].split(":")
                            x = int(sp[0])
                            y = int(sp[1])
                            what = self.board_reference[y][x]
                            if what == "s":
                                self.board_reference[y][x] = "x"
                                self.ship_rem -= 1
                            elif what == '':
                                self.board_reference[y][x] = "m"
                            self.out_queue.put(self.board_reference[y][x])
                            if self.ship_rem == 0:
                                self.out_queue.put("win")
                                self.app.popup("info", "You have lost!")
                                self.reset()
                                continue
                            self.state = "playing_p"
                            self.info.configure(text="Your turn.")
                            self.wipe_board(self.en_board_ref)
                            self.board_but.configure(text="Show your board", command=lambda: self.toggle('b', 'm'))
                            self.show_but.configure(text="Show ships", state="disabled", command=lambda: self.toggle('s', True))
                    if msg == "win":
                        self.app.popup("info", "You have won!")
                        self.reset()
                    if msg[0] == "*":
                        self.chat_queue.put("Them: " + msg[1:])
                elif self.state == "playing_c":
                    if self.app.c_s == "s":
                        self.state = "playing_p"
                        self.info.configure(text="Your turn.")
                        self.wipe_board()
                    else:
                        self.state = "playing_w"
                        self.info.configure(text="Other player's turn.")
                        self.wipe_board(state="disabled")
                    self.board_but.configure(state="normal")
                    print(self.state)

            time.sleep(0.5)

    def handler(self, c, addr):
        while not self.disc_flag.is_set():
            try:
                ready = select.select([c], [], [], 0.5)
                if ready[0]:
                    reply = c.recv(1024)
                    reply = reply.decode('utf-8')
                    print("received", reply)
                    if not reply:
                        self.app.popup("warning", "Server did not respond!")
                        break
                    self.in_queue.put(reply)

                if not self.out_queue.empty():
                    msg = self.out_queue.get()
                    print("sending", msg)
                    c.send(msg.encode())

            except Exception as e:
                if str(e) in ["[WinError 10035] A non-blocking socket operation could not be completed immediately",
                              "timed out"]:
                    continue
                print(e)
                break
            
        c.close()
        self.disc_flag.clear()
        if self.app.c_s == "s":
            self.app.set_display(self.app.wait)
            t = threading.Thread(target=self.app.wait.listen)
            t.setDaemon(True)
            t.start()
        elif self.app.c_s == "c":
            self.app.popup("error", "Server closed connection, closing.")
            self.app.root.after(100, self.app.root.destroy)

    def wipe_board(self, board=(), preserve=('x', 'm'), state="normal"):
        for x in range(11):
            for y in range(11):
                if x != 0 and y != 0:
                    if (x+y) % 2 == 0:
                        col1 = 87
                    else:
                        col1 = 72
                    if state == "disabled":
                        col1 -= 20
                    if board:
                        if board[y][x] not in preserve:
                            self.board_gui[y][x].configure(text="", bg="grey{}".format(col1), state=state)
                        else:
                            if board[y][x] == "s":
                                col2 = "chartreuse2"
                            if board[y][x] == "x":
                                col2 = "firebrick1"
                            if board[y][x] == "m":
                                col2 = "yellow2"
                            self.board_gui[y][x].configure(text="", bg=col2, state='disabled')
                    else:
                        self.board_gui[y][x].configure(text="", bg="grey{}".format(col1), state=state)

    def click(self, x, y):
        if self.state == "select":
            if self.board_gui[y][x].cget("bg") == "olivedrab1":
                self.selected.remove((x, y))
                if (x+y) % 2 == 0:
                    col = "gray87"
                else:
                    col = "gray72"
                self.board_gui[y][x].configure(bg=col)
                self.ship_no += 1
                self.action_but.configure(state="disabled")

                self.info.configure(text="Select your ship positions. ({})".format(self.ship_no))

            elif self.ship_no >= 1:
                self.board_gui[y][x].configure(bg='olivedrab1')
                self.selected.append((x, y))
                self.ship_no -= 1
                if self.ship_no == 0:
                    self.action_but.configure(state="normal")

                self.info.configure(text="Select your ship positions. ({})".format(self.ship_no))

        if self.state == "playing_p":
            self.wipe_board(self.en_board_ref)
            self.board_gui[y][x].configure(bg="tomato")
            self.action_but.configure(state="normal")
            self.selected = ((x, y),)

    def action(self):
        # Confirm position
        if self.state == "select":
            for x, y in self.selected:
                self.board_gui[y][x].configure(bg="chartreuse2")
                self.action_but.configure(state='disabled')
                self.info.configure(text="Waiting for other player...")
                self.board_reference[y][x] = 's'
            self.out_queue.put("done")
            self.state = "picked"

        if self.state == "playing_p":
            self.info.configure(text="Waiting for response...")
            x, y = self.selected[0]
            self.action_but.configure(state='disabled')
            self.wipe_board(self.en_board_ref, state="disabled")
            self.board_but.configure(text="Show your board", command=lambda: self.toggle('b', 'm'))
            self.show_but.configure(text="Show ships", state="disabled", command=lambda: self.toggle('s', True))
            self.state = "playing_w"
            self.out_queue.put("?{}:{}".format(x, y))
            try:
                what = self.in_queue.get(timeout=3)
            except queue.Empty:
                self.app.popup("error", "Received no response! Closing connection.")
                self.disc_flag.set()
                return
            self.en_board_ref[y][x] = what
            if what == "x":
                col = "firebrick1"
                text = "Hit!"
            else:
                col = "yellow2"
                text = "Miss!"
            self.board_gui[y][x].configure(bg=col)
            self.info.configure(text=text)
            self.app.root.after(1000, lambda: self.info.configure(text="Other player's turn."))

    def toggle(self, what, how):
        # board
        b = ()
        p = ('x', 'm')
        s = "normal"
        if what == "b":
            if how == "m":
                b = self.board_reference
                self.board_but.configure(text="Show enemy board", command=lambda: self.toggle('b', 'e'))
                self.info.configure(text="Your board. ({} ships left)".format(self.ship_rem))
                s = 'disabled'
                self.action_but.configure(state="disabled")
                self.show_but.configure(state="normal")
            elif how == "e":
                b = self.en_board_ref
                self.board_but.configure(text="Show your board", command=lambda: self.toggle('b', 'm'))
                t = "Other player's turn."
                s = 'disabled'
                if self.state == "playing_p":
                    self.action_but.configure(state="normal")
                    s = 'normal'
                    t = "Your turn."
                self.info.configure(text=t)
                self.show_but.configure(state="disabled")
        if what == "s":
            if how:
                b = self.board_reference
                p = ('x', 'm', 's')
                self.show_but.configure(text="Hide ships", command=lambda: self.toggle('s', False))
                s = 'disabled'
            else:
                b = self.board_reference
                self.show_but.configure(text="Show ships", command=lambda: self.toggle('s', True))
                s = 'disabled'
        self.wipe_board(board=b, preserve=p, state=s)

    def set_state(self, to):
        self.state = to

    def reset(self):
        # CLEANUP
        self.state = "select"
        self.selected = []
        self.ship_no = 21
        self.ship_rem = 21
        self.info.configure(text="Select ship positions. ({})".format(self.ship_no))
        self.board_but.configure(text="Show your board", state='disabled', command=lambda: self.toggle('b', 'm'))
        self.show_but.configure(text="Show ships", state="disabled", command=lambda: self.toggle('s', True))
        self.en_board_ref = [['' for v in range(11)] for c in range(11)]
        self.board_reference = [['' for v in range(11)] for c in range(11)]
        self.wipe_board()

    def draw(self):
        self.window.start()
        self.info.grid(column=0, row=0, columnspan=11)
        for y, row in enumerate(self.board_gui):
            for x, cell in enumerate(row):
                cell.grid(column=x, row=y+1, sticky="nesw")
        self.action_but.grid(column=0, row=12)
        self.show_but.grid(column=5, row=12, columnspan=2, sticky="WE")
        self.board_but.grid(column=7, row=12, columnspan=5, sticky="WE")
        self.loop = True

    def undraw(self):
        self.info.grid_forget()
        for y, row in enumerate(self.board_gui):
            for x, cell in enumerate(row):
                cell.grid_forget()
        self.action_but.grid_forget()
        self.show_but.grid_forget()
        self.board_but.grid_forget()
        self.loop = False

    def start_chat(self):
        self.c = ChatWindow(self.app)
        while 1:
            if not self.chat_queue.empty():
                m = self.chat_queue.get()
                self.c.chat_window.add_text(m)

Main = App()
