# coding=gbk

import tkinter as tk
from tkinter import scrolledtext, ttk  # scrolledtext: A Tkinter widget that provides a text area with scrollbars. ttk: Themed Tkinter widgets that look more modern
import threading  # Allows running processes in parallel (prevents UI freezing)
from datetime import datetime
from openai import OpenAI


class ChatbotGUI:
    def __init__(self, root, key='xxx', model='gpt-3.5-turbo'):
        # Set the window title, size, and background color
        self.root = root
        self.root.title('AI Assistant Chat')
        self.root.geometry('800x600')
        self.root.attributes('-topmost', True)
        mac.after(2000, lambda: mac.attributes('-topmost', False))
        self.root.configure(bg='#f0f0f0')  # light gray

        # Initialize OpenAI client
        self.api_key = key  # Better to use environment variables
        self.llm = OpenAI(api_key=self.api_key)
        self.model_name = model  # Using OpenAI model

        # Generate a unique filename for this session
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        self.log_file = f'conversation_{timestamp}_log.txt'

        # Initialize conversation history
        self.conversation_history = []

        # Create the main frame
        main_frame = tk.Frame(root, bg='#f0f0f0')  # a container widget that organizes other widgets (the primary container for all elements)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)  # makes frames expand to fill available space, and adds padding space around the frames

        # Create a frame for the chat history
        history_frame = tk.Frame(main_frame, bg='#f0f0f0')  # light gray
        history_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Chat history text area
        self.chat_history = scrolledtext.ScrolledText(
            history_frame,
            wrap=tk.WORD,  # wraps text at word boundaries
            bg='#5350e6',  # blue purple
            font=('Arial', 10),
            borderwidth=1,
            relief='solid'
        )
        self.chat_history.pack(fill=tk.BOTH, expand=True)
        self.chat_history.config(state=tk.DISABLED)  # prevents users from editing the chat history directly

        # Input frame for user message and send button
        input_frame = tk.Frame(main_frame, bg='#f0f0f0')  # light gray
        input_frame.pack(fill=tk.X, pady=10)

        # User input text field
        self.user_input = tk.Text(
            input_frame,
            height=3,  # multi-line input (height=3 means 3 lines tall)
            wrap=tk.WORD,
            font=('Arial', 10),
            borderwidth=1,
            relief='solid'
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))  # expand horizontally, but not vertically
        self.user_input.bind('<Return>', self.on_enter_pressed)  # connects the Enter key to the send function

        # Create a button style
        style = ttk.Style()
        style.configure('TButton', font=('Arial', 10))

        # Send button
        self.send_button = ttk.Button(
            input_frame,
            text='Send',
            command=self.send_message,  # what function to call when clicked
            style='TButton'
        )
        self.send_button.pack(side=tk.RIGHT, padx=5)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set('Ready to chat!')
        self.status_bar = tk.Label(
            root,
            textvariable=self.status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,  # aligns text to the west (left)
            bg='#c9c56d',  # light yellow
            fg='#030303',  # black
            font=('Arial', 8)
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)  # bottom, stretches horizontally

        # Welcome message
        self.display_message('AI Assistant', 'Hello! How can I help you today?')

        # Set focus to input field by default
        self.user_input.focus_set()

# specifically defined function
    def on_enter_pressed(self, event):
        """Handle Enter key press - send message but allow Shift+Enter for new line"""
        if not event.state & 0x1:  # Check if Shift(0x1) is not pressed
            self.send_message()
            return 'break'  # special return in tkinter to tell it stop the default behavior (newline)

    def display_message(self, sender, message):
        """Display a message in the chat histor"""
        self.chat_history.config(state=tk.NORMAL)  # set it can be editable

        # Format based on sender
        if sender == 'You':
            self.chat_history.insert(tk.END, f'\n{sender}: ', 'user')  # insert context to the back of content
            self.chat_history.insert(tk.END, f'{message}\n', 'user_msg')
        else:
            self.chat_history.insert(tk.END, f'\n{sender}: ', 'assistant')
            self.chat_history.insert(tk.END, f'{message}\n', 'assistant_msg')

        # Add tags for styling, define its style
        self.chat_history.tag_config('user', font=('Arial', 10, 'bold'), foreground='#0000CC')
        self.chat_history.tag_config('user_msg', font=('Arial', 10))
        self.chat_history.tag_config('assistant', font=('Arial', 10, 'bold'), foreground='#CC0000')
        self.chat_history.tag_config('assistant_msg', font=('Arial', 10))

        # Scroll to the bottom
        self.chat_history.see(tk.END)  # operate the scrolls to show the newest message
        self.chat_history.config(state=tk.DISABLED)  # reset it to be frozen

        # Save to file
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f'{sender}: {message}\n\n')

    def send_message(self):
        """Send the user message to the AI and get a respons"""
        # Get user input
        user_message = self.user_input.get('1.0', tk.END).strip()

        if not user_message:
            return

        # Clear input field
        self.user_input.delete('1.0', tk.END)

        # Display user message
        self.display_message('You', user_message)

        # Add to conversation history
        self.conversation_history.append({'role': 'user', 'content': user_message})

        # Update status
        self.status_var.set('AI is thinking...')

        # Create a thread for API call to avoid freezing the UI
        threading.Thread(target=self.get_ai_response).start()

    def get_ai_response(self):
        """Get response from AI in a separate threa"""
        try:
            # Get response from AI
            response = self.llm.chat.completions.create(
                model=self.model_name,
                messages=self.conversation_history,
                temperature=0.7,
            )

            # Extract the AI's message
            ai_response = response.choices[0].message.content

            # Append the AI's response to the conversation history
            self.conversation_history.append({'role': 'assistant', 'content': ai_response})

            # Display the AI's response
            self.root.after(0, lambda: self.display_message('AI Assistant', ai_response))

            # Update status
            self.root.after(0, lambda: self.status_var.set('Ready to chat!'))

        except Exception as e:
            error_message = f'Error: {str(e)}'
            self.root.after(0, lambda: self.display_message('System', error_message))
            self.root.after(0, lambda: self.status_var.set('Error occurred'))


if __name__ == '__main__':
    mac = tk.Tk()
    mac.focus_force()
    app = ChatbotGUI(mac)
    mac.mainloop()
