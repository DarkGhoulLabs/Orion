from core.llm_interface import ask_orion
from core.command_router import route_command
from core.state_manager import get_pending

def main():
    print("ORION online. Type 'exit' to quit\n")

    while True:
        user_input = input("You:")
        if user_input.lower()=="exit":
            print("ORION: Shutting down.")
            break

        pending = get_pending()
        if pending:
            #print("DEBUG: confrimation branch triggered")
            result = route_command(user_input)
            print(f"ORION: {result}\n")
            continue

        llm_response = ask_orion(user_input)
        result = route_command(llm_response)

        print(f"ORION: {result}\n")

if __name__=="__main__":
    main()