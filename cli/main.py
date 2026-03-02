from core.llm_interface import ask_orion

def main():
    print("ORION online. Type 'exit' to quit\n")

    while True:
        user_input = input("You:")
        if user_input.lower()=="exit":
            print("ORION: Shutting down.")
            break
        response = ask_orion(user_input)
        print(f"ORION: {response}\n")

if __name__=="__main__":
    main()