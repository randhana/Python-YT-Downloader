from pytube import YouTube

def Download(link):
    youtubeObject = YouTube(link)
    youtubeObject = youtubeObject.streams.get_by_resolution("720p")

    try:
        youtubeObject.download("Downloads")
    except:
        print("There has been an error in downloading")
    print("This download has completed!")

link = input("Put your youtube link here! URL: ")
Download(link)