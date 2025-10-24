import avatarImage from "@/assets/avatar.jpeg";

const Avatar = () => {
  return (
    <div className="flex justify-center">
      <div className="relative">
        <div className="absolute inset-0 animate-pulse-glow rounded-full" />
        <img
          src={avatarImage}
          alt=""
          className="relative h-33 w-32 rounded-full border-2 object-cover shadow-elegant"
        />
      </div>
    </div>
  );
};

export default Avatar;
