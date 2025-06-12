# coding=gbk

from openai import OpenAI
import datetime

# Initialize the OpenAI client
api_key = 'xxx'  # Better to use environment variables
llm = OpenAI(api_key=api_key)

# Note: 'claude-3-7-sonnet' is an Anthropic model, not OpenAI
# You should use an OpenAI model like 'gpt-4-turbo' or 'gpt-3.5-turbo'
model_name = 'gpt-4-turbo'  # Changed from claude to an OpenAI model


def chat_with_ai():
    print("Chat with AI Assistant (type \'quit\' to exit)")
    print('----------------------------------------')

    conversation_history = []

    while True:
        # Get user input
        user_input = input('\n>> You: ')

        # Check if user wants to exit
        if user_input.lower() in ['quit', 'exit', 'bye']:
            print('Ending conversation. Goodbye!')
            break

        # Append the user's message to the conversation history
        conversation_history.append({'role': 'user', 'content': user_input})

        try:
            # Get response from AI
            response = llm.chat.completions.create(
                model=model_name,
                messages=conversation_history,
                temperature=0.7,
            )

            # Extract the AI's message
            ai_response = response.choices[0].message.content

            # Append the AI's response to the conversation history
            conversation_history.append({'role': 'assistant', 'content': ai_response})

            # Print the AI's response
            print('\n>> AI: ' + ai_response)

        except Exception as e:
            print(f'\nError: {e}')

    # Option to save conversation
    if conversation_history:
        save = input('\nWould you like to save this conversation? (y/n): ')
        if save.lower() == 'y':
            with open(f'conversation_{datetime.datetime.today().strftime('%Y%m%d%H%M')}_log.txt', 'w', encoding='utf-8') as f:
                for message in conversation_history:
                    f.write(f'{message['role'].upper()}: {message['content']}\n\n')
            print('Conversation saved to conversation_log.txt')


if __name__ == '__main__':
    chat_with_ai()
